<template>
  <div class="app-shell">
    <header class="app-header">
      <div
        class="brand-mark"
        aria-hidden="true"
      >
        S
      </div>
      <div class="brand-copy">
        <strong>沙发场景提示词工作台</strong>
        <span>SOFA SCENE STUDIO</span>
      </div>
      <nav
        v-if="showNavigation"
        class="app-nav"
        aria-label="主导航"
      >
        <router-link to="/">
          工作台
        </router-link>
        <router-link to="/admin">
          系统管理
        </router-link>
      </nav>
    </header>
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const showNavigation = computed(() => route.path !== '/login')
</script>

<style>
:root {
  color: #26352f;
  background: #f4f0e8;
  font-family: "Noto Sans SC", "Microsoft YaHei", "PingFang SC", sans-serif;
  font-synthesis: none;
  --sofa-ink: #26352f;
  --sofa-muted: #748078;
  --sofa-green: #315f4c;
  --sofa-green-dark: #24483a;
  --sofa-green-soft: #e4ede7;
  --sofa-cream: #f4f0e8;
  --sofa-paper: #fffdf8;
  --sofa-clay: #b96f4d;
  --sofa-line: #ded8cc;
  --sofa-shadow: 0 16px 38px rgb(62 50 38 / 9%);
  --el-color-primary: #315f4c;
  --el-color-primary-light-3: #648577;
  --el-color-primary-light-5: #8fa79d;
  --el-color-primary-light-7: #bac9c2;
  --el-color-primary-light-8: #d1ddd7;
  --el-color-primary-light-9: #e8eeeb;
  --el-color-primary-dark-2: #274c3d;
  --el-color-success: #4f7c61;
  --el-color-warning: #b8813c;
  --el-color-danger: #ad5648;
  --el-border-color: #ded8cc;
  --el-border-color-light: #e9e4da;
  --el-fill-color-light: #f7f4ed;
  --el-bg-color: #fffdf8;
  --el-text-color-primary: #26352f;
  --el-text-color-regular: #56635d;
  --el-border-radius-base: 10px;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
  background:
    radial-gradient(circle at 12% 8%, rgb(185 111 77 / 8%), transparent 27%),
    linear-gradient(135deg, #f7f3eb 0%, #f1eee6 100%);
}

button,
input,
textarea,
select {
  font: inherit;
}

.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 13px;
  height: 64px;
  padding: 0 24px;
  flex: none;
  z-index: 20;
  color: #f9f5ec;
  background: linear-gradient(115deg, #233e34, #315f4c 72%, #3d6856);
  box-shadow: 0 6px 24px rgb(33 58 48 / 18%);
}

.app-header strong {
  white-space: nowrap;
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-size: 16px;
  letter-spacing: .06em;
}

.brand-copy {
  display: grid;
  gap: 2px;
}

.brand-copy span {
  color: rgb(255 255 255 / 55%);
  font-family: Georgia, serif;
  font-size: 8px;
  letter-spacing: .22em;
}

.app-nav {
  display: flex;
  align-self: stretch;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.app-nav a {
  display: flex;
  height: 100%;
  align-items: center;
  height: 38px;
  padding: 0 16px;
  border: 1px solid transparent;
  border-radius: 10px;
  color: rgb(255 255 255 / 68%);
  font-size: 14px;
  text-decoration: none;
  transition: color .2s ease, background .2s ease, border-color .2s ease;
}

.app-nav a:hover {
  color: #fff;
  background: rgb(255 255 255 / 8%);
}

.app-nav a.router-link-active {
  border-color: rgb(255 255 255 / 13%);
  color: #fff;
  background: rgb(255 255 255 / 12%);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 10%);
}

.brand-mark {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border: 1px solid rgb(255 255 255 / 28%);
  border-radius: 12px 12px 12px 4px;
  color: #315f4c;
  background: #efe3cf;
  box-shadow: 0 5px 14px rgb(16 43 32 / 24%);
  font-family: Georgia, serif;
  font-size: 20px;
  font-weight: 800;
}

.el-button {
  font-weight: 500;
}

.el-button:not(.is-circle) {
  min-height: 36px;
  padding-inline: 15px;
}

.el-dialog {
  overflow: hidden;
  border: 1px solid rgb(222 216 204 / 80%);
  border-radius: 18px;
  background: var(--sofa-paper);
  box-shadow: 0 30px 80px rgb(44 38 30 / 20%);
}

.el-dialog__header {
  padding: 20px 24px 16px;
  border-bottom: 1px solid var(--sofa-line);
}

.el-dialog__title {
  color: var(--sofa-ink);
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-weight: 700;
}

.el-dialog__body {
  padding: 22px 24px;
}

.el-input__wrapper,
.el-select__wrapper,
.el-textarea__inner {
  box-shadow: 0 0 0 1px var(--sofa-line) inset;
}

.el-input__wrapper:hover,
.el-select__wrapper:hover,
.el-textarea__inner:hover {
  box-shadow: 0 0 0 1px #9fac9f inset;
}

@media (max-width: 560px) {
  .app-header {
    height: 58px;
    padding: 0 8px 0 12px;
  }

  .brand-copy {
    overflow: hidden;
  }

  .brand-copy strong {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .brand-copy span { display: none; }

  .app-nav a {
    padding: 0 8px;
    white-space: nowrap;
  }
}

.app-main {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
