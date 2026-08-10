<template>
  <main class="login-page">
    <section
      class="login-story"
      aria-label="产品介绍"
    >
      <div class="story-kicker">
        SOFA SCENE STUDIO
      </div>
      <h2>让每一张沙发产品图，<br><em>自然融入理想生活。</em></h2>
      <p>从参考场景到高质量提示词，在一个专注、可靠的工作台中完成创意生产。</p>
      <div class="story-meta">
        <span>场景理解</span><span>方向审核</span><span>版本沉淀</span>
      </div>
    </section>
    <form
      class="login-card"
      @submit.prevent="submit"
    >
      <div class="login-brand">
        S
      </div>
      <div class="login-heading">
        <span>管理员登录</span>
        <h1>登录工作台</h1>
        <p>使用管理员账号继续创作</p>
      </div>
      <label>
        用户名
        <input
          v-model="username"
          name="username"
          autocomplete="username"
        >
      </label>
      <label>
        密码
        <input
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
        >
      </label>
      <p
        v-if="error"
        class="error"
        role="alert"
      >
        {{ error }}
      </p>
      <button
        type="submit"
        :disabled="submitting"
      >
        {{ submitting ? '登录中…' : '登录' }}
      </button>
    </form>
  </main>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'

const router = useRouter()
/** 用户输入的登录用户名。 */
const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  submitting.value = true
  error.value = ''
  try {
    await api.post('/api/v1/auth/login', {
      username: username.value,
      password: password.value,
    })
    await router.push('/')
  } catch (reason: unknown) {
    const message = (reason as { response?: { data?: { error?: { message?: string } } } })
      .response?.data?.error?.message
    error.value = message || '登录失败，请检查用户名和密码'
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  grid-template-columns: minmax(420px, 1.15fr) minmax(380px, .85fr);
  gap: 8vw;
  align-items: center;
  padding: clamp(32px, 6vw, 96px);
  overflow: hidden;
  background:
    radial-gradient(circle at 15% 75%, rgb(185 111 77 / 16%), transparent 28%),
    linear-gradient(120deg, #e9e2d5 0 51%, #f8f5ee 51% 100%);
  isolation: isolate;
}

.login-page::before,
.login-page::after {
  position: absolute;
  z-index: -1;
  border: 1px solid rgb(49 95 76 / 12%);
  border-radius: 50%;
  content: "";
}

.login-page::before { width: 420px; height: 420px; left: -150px; top: -180px; }
.login-page::after { width: 260px; height: 260px; right: -80px; bottom: -100px; }

.login-story { max-width: 680px; color: #294338; }
.story-kicker { margin-bottom: 28px; color: #9b664c; font: 700 11px/1.2 Georgia, serif; letter-spacing: .3em; }
.login-story h2 { margin: 0; font: 600 clamp(36px, 4.5vw, 68px)/1.22 "Noto Serif SC", "Songti SC", serif; letter-spacing: -.04em; }
.login-story h2 em { color: #9b664c; font-style: normal; }
.login-story p { max-width: 560px; margin: 28px 0 36px; color: #617068; font-size: 16px; line-height: 1.9; }
.story-meta { display: flex; gap: 10px; }
.story-meta span { padding: 7px 13px; border: 1px solid rgb(49 95 76 / 18%); border-radius: 999px; color: #52655c; font-size: 12px; letter-spacing: .08em; }

.login-card {
  display: grid;
  gap: 20px;
  width: min(440px, 100%);
  justify-self: center;
  padding: clamp(30px, 4vw, 48px);
  border: 1px solid rgb(222 216 204 / 80%);
  border-radius: 26px 26px 26px 8px;
  background: rgb(255 253 248 / 92%);
  box-shadow: 0 30px 70px rgb(65 53 40 / 14%);
  backdrop-filter: blur(14px);
}
.login-brand {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 14px 14px 14px 5px;
  background: #315f4c;
  color: #f5e9d7;
  box-shadow: 0 9px 18px rgb(49 95 76 / 20%);
  font-family: Georgia, serif;
  font-size: 24px;
  font-weight: 800;
}
h1, p { margin: 0; }
.login-heading { display: grid; gap: 5px; margin-bottom: 2px; }
.login-heading span { color: #9b664c; font-size: 12px; font-weight: 700; letter-spacing: .16em; }
.login-heading h1 { color: #26352f; font: 700 28px/1.4 "Noto Serif SC", "Songti SC", serif; }
.login-heading p { color: #7b847f; font-size: 13px; }
label { display: grid; gap: 8px; color: #4b5a53; font-size: 13px; font-weight: 600; }
input {
  width: 100%;
  min-height: 46px;
  padding: 11px 14px;
  border: 1px solid #d9d2c6;
  border-radius: 11px;
  outline: none;
  color: #26352f;
  background: #fffefa;
  transition: border-color .2s ease, box-shadow .2s ease;
}
input:focus { border-color: #527764; box-shadow: 0 0 0 4px rgb(49 95 76 / 10%); }
button {
  min-height: 46px;
  padding: 12px;
  border: 0;
  border-radius: 11px;
  background: linear-gradient(135deg, #315f4c, #24483a);
  color: white;
  cursor: pointer;
  font-weight: 600;
  letter-spacing: .1em;
  box-shadow: 0 9px 20px rgb(49 95 76 / 18%);
  transition: transform .2s ease, box-shadow .2s ease;
}
button:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 12px 24px rgb(49 95 76 / 24%); }
button:disabled { cursor: not-allowed; opacity: .65; }
.error { color: #c0392b; font-size: 14px; }

@media (max-width: 900px) {
  .login-page { grid-template-columns: 1fr; padding: 32px 20px; background: linear-gradient(155deg, #e9e2d5, #f8f5ee); }
  .login-story { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  button { transition: none; }
}
</style>
