package com.company.bj.voice.cloud.memory.companion;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import java.util.List;
import java.util.Optional;

/**
 * 记忆更新服务。
 *
 * <p>用户改口时（"我妈妈叫李芳" → "我妈妈叫王芳"），旧事实必须<b>归档而非删除</b>。
 *
 * <p><b>为什么不物理删除</b>：
 * <ul>
 *   <li><b>可追溯</b> —— 用户问"我以前说我妈妈叫什么"，机器人能答上来；</li>
 *   <li><b>可纠错</b> —— 归档错了还能恢复，删了就没了；</li>
 *   <li><b>可审计</b> —— 记忆系统出错时能回溯"我当时是怎么记的"。</li>
 * </ul>
 *
 * <p><b>幂等键用语义指纹</b>（{@link SemanticFingerprint}）：
 * 同一句话说两次不会写两遍，用户的同一件事被反复提起也不会膨胀存储。
 */
public class MemoryUpdateService {

    /** 查找潜在取代者时的候选上限。 */
    private static final int ARCHIVE_LOOKUP_LIMIT = 20;

    /** 主体词元的长度（"我妈妈"三个字）。 */
    private static final int SUBJECT_PREFIX_LENGTH = 3;

    /** 长期记忆存储。 */
    private final LongTermStore store;

    /** 语义指纹计算器。 */
    private final FingerprintCalculator fingerprint;

    /**
     * 构造记忆更新服务。
     *
     * @param store       长期记忆存储
     * @param fingerprint 语义指纹计算器
     */
    public MemoryUpdateService(LongTermStore store, FingerprintCalculator fingerprint) {
        this.store = store;
        this.fingerprint = fingerprint;
    }

    /**
     * 写入或更新一条记忆。
     *
     * <p>流程：先按指纹找是否已有等价内容 ——
     * <ul>
     *   <li>有且等价：<b>不重复写</b>，直接返回已有记录；</li>
     *   <li>有但内容冲突（同主体不同值）：<b>归档旧记录 + 写入新记录</b>；</li>
     *   <li>没有：直接写入。</li>
     * </ul>
     *
     * @param content 记忆内容
     * @return 更新结果
     */
    public UpdateOutcome upsert(String content) {
        String normalized = fingerprint.of(content);
        if (normalized.isEmpty()) {
            return UpdateOutcome.rejected("记忆内容为空");
        }

        List<MemoryRecord> existing = store.search(content, ARCHIVE_LOOKUP_LIMIT);
        Optional<MemoryRecord> equivalent = existing.stream()
            .filter(record -> normalized.equals(fingerprint.of(record.content())))
            .findFirst();

        if (equivalent.isPresent()) {
            // 同一件事又说了一遍：不写第二条，避免存储膨胀。
            return UpdateOutcome.unchanged(equivalent.get());
        }

        Optional<MemoryRecord> superseded = findSuperseded(existing, normalized);

        MemoryRecord written = store.remember(content);
        if (superseded.isPresent()) {
            store.forget(superseded.get().id());
        }

        return superseded.isPresent()
            ? UpdateOutcome.updated(written, superseded.get())
            : UpdateOutcome.created(written);
    }

    /**
     * 在候选记录里找出被新内容取代的那条。
     *
     * <p>取代的判定条件：<b>同一主体但值不同</b> ——
     * 例如"我妈妈叫李芳"与"我妈妈叫王芳"说的是同一件事的两个版本。
     * 仅仅"同类"就归档过于激进：用户说"我妈妈叫李芳"和"我姐姐叫李芳"
     * 都属关系事实，却不该互相取代。
     *
     * @param candidates 候选记录
     * @param normalized 新内容的指纹
     * @return 被取代的记录；不存在时为空
     */
    private Optional<MemoryRecord> findSuperseded(List<MemoryRecord> candidates, String normalized) {
        for (MemoryRecord record : candidates) {
            String recordFingerprint = fingerprint.of(record.content());
            if (recordFingerprint.isEmpty() || recordFingerprint.equals(normalized)) {
                continue;
            }
            if (sharesSubject(record.content(), normalized)) {
                return Optional.of(record);
            }
        }
        return Optional.empty();
    }

    /**
     * 判断两段内容是否指向同一个主体。
     *
     * <p>判断依据是<b>首个名词性词元</b>是否一致 ——
     * "我妈妈叫李芳"与"我妈妈叫王芳"的主体都是"我妈妈"。
     *
     * @param left            左侧内容
     * @param rightFingerprint 右侧内容的指纹
     * @return 主体一致返回 {@code true}
     */
    private boolean sharesSubject(String left, String rightFingerprint) {
        String leftFingerprint = fingerprint.of(left);
        if (leftFingerprint.isEmpty() || rightFingerprint.isEmpty()) {
            return false;
        }
        if (leftFingerprint.length() <= SUBJECT_PREFIX_LENGTH
            || rightFingerprint.length() <= SUBJECT_PREFIX_LENGTH) {
            return false;
        }
        String leftSubject = leftFingerprint.substring(0, SUBJECT_PREFIX_LENGTH);
        String rightSubject = rightFingerprint.substring(0, SUBJECT_PREFIX_LENGTH);
        return leftSubject.equals(rightSubject);
    }

    /**
     * 一次记忆更新的结果。
     *
     * @param status     更新状态
     * @param record     生效的记录；被拒时为空
     * @param superseded 被归档的旧记录；未发生取代时为空
     * @param message    说明；用于向调用方解释结果
     */
    public record UpdateOutcome(
        UpdateStatus status, MemoryRecord record, MemoryRecord superseded, String message) {

        /**
         * 更新状态。
         */
        public enum UpdateStatus {

            /** 新建了一条记录。 */
            CREATED,

            /** 覆盖了旧记录（旧记录已归档）。 */
            UPDATED,

            /** 内容已存在，未重复写入。 */
            UNCHANGED,

            /** 内容非法，未写入。 */
            REJECTED
        }

        /**
         * 构造一个"新建"结果。
         *
         * @param record 新记录
         * @return 更新结果
         */
        public static UpdateOutcome created(MemoryRecord record) {
            return new UpdateOutcome(UpdateStatus.CREATED, record, null, "已写入新记忆");
        }

        /**
         * 构造一个"覆盖"结果。
         *
         * @param record     新记录
         * @param superseded 被归档的旧记录
         * @return 更新结果
         */
        public static UpdateOutcome updated(MemoryRecord record, MemoryRecord superseded) {
            return new UpdateOutcome(UpdateStatus.UPDATED, record, superseded, "已覆盖旧记忆并归档旧版本");
        }

        /**
         * 构造一个"未变化"结果。
         *
         * @param record 已有记录
         * @return 更新结果
         */
        public static UpdateOutcome unchanged(MemoryRecord record) {
            return new UpdateOutcome(UpdateStatus.UNCHANGED, record, null, "记忆内容未变化");
        }

        /**
         * 构造一个"被拒"结果。
         *
         * @param message 拒绝原因
         * @return 更新结果
         */
        public static UpdateOutcome rejected(String message) {
            return new UpdateOutcome(UpdateStatus.REJECTED, null, null, message);
        }

        /**
         * 判断本次更新是否归档了旧记录。
         *
         * @return 发生归档返回 {@code true}
         */
        public boolean archivedPrevious() {
            return superseded != null;
        }
    }
}
