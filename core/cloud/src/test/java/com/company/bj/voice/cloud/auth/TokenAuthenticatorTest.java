package com.company.bj.voice.cloud.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

class TokenAuthenticatorTest {

    @Test
    void 有效凭据通过鉴权() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        assertThatCode(() -> authenticator.authenticate("secret-token")).doesNotThrowAnyException();
    }

    @Test
    void 无效凭据被拒绝() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        assertThatThrownBy(() -> authenticator.authenticate("wrong-token"))
                .isInstanceOf(AuthenticationException.class);
    }

    @Test
    void 缺失凭据被拒绝() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        assertThatThrownBy(() -> authenticator.authenticate(null))
                .isInstanceOf(AuthenticationException.class);
    }

    @Test
    void 空凭据被拒绝() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        assertThatThrownBy(() -> authenticator.authenticate(""))
                .isInstanceOf(AuthenticationException.class);
    }

    @Test
    void 失败信息不区分缺失与错误() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        String missingMessage = null;
        try {
            authenticator.authenticate(null);
        } catch (AuthenticationException error) {
            missingMessage = error.getMessage();
        }

        String wrongMessage = null;
        try {
            authenticator.authenticate("wrong-token");
        } catch (AuthenticationException error) {
            wrongMessage = error.getMessage();
        }

        // 区分"缺失"与"错误"会给攻击者多一条信息。
        assertThat(missingMessage).isEqualTo(wrongMessage);
    }

    @Test
    void 失败信息不含凭据本身() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        assertThatThrownBy(() -> authenticator.authenticate("leaked-value"))
                .hasMessageNotContaining("leaked-value");
    }

    @Test
    void 未配置凭据时不启用鉴权() {
        TokenAuthenticator authenticator = new TokenAuthenticator("");

        assertThat(authenticator.isEnabled()).isFalse();
        assertThatCode(() -> authenticator.authenticate(null)).doesNotThrowAnyException();
        assertThatCode(() -> authenticator.authenticate("anything")).doesNotThrowAnyException();
    }

    @Test
    void 凭据为null时视为未启用() {
        TokenAuthenticator authenticator = new TokenAuthenticator(null);

        assertThat(authenticator.isEnabled()).isFalse();
    }

    @Test
    void 长度不同的凭据被拒绝() {
        TokenAuthenticator authenticator = new TokenAuthenticator("secret-token");

        assertThatThrownBy(() -> authenticator.authenticate("secret"))
                .isInstanceOf(AuthenticationException.class);
    }
}
