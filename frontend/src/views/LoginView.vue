<template>
  <main class="login-page">
    <form
      class="login-card"
      @submit.prevent="submit"
    >
      <div class="login-brand">
        S
      </div>
      <h1>管理员登录</h1>
      <p>沙发场景提示词工作台</p>
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
  place-items: center;
  padding: 24px;
  background: linear-gradient(135deg, #eef4f1, #f6f7f9 55%, #edf1f7);
}
.login-card {
  display: grid;
  gap: 16px;
  width: min(400px, 100%);
  padding: 36px;
  border: 1px solid #e0e5ea;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 18px 50px rgb(34 45 62 / 10%);
}
.login-brand {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: #79d3a5;
  color: #1d2c24;
  font-size: 22px;
  font-weight: 800;
}
h1, p { margin: 0; }
label { display: grid; gap: 7px; font-size: 14px; color: #46505e; }
input {
  width: 100%;
  padding: 11px 12px;
  border: 1px solid #cfd6df;
  border-radius: 8px;
  outline: none;
}
input:focus { border-color: #409eff; box-shadow: 0 0 0 3px rgb(64 158 255 / 12%); }
button {
  padding: 12px;
  border: 0;
  border-radius: 8px;
  background: #2f7e5a;
  color: white;
  cursor: pointer;
}
.error { color: #c0392b; font-size: 14px; }
</style>
