<template>
  <div class="app-shell">
    <header class="app-header">
      <div
        class="brand-mark"
        aria-hidden="true"
      >
        S
      </div>
      <strong>沙发场景提示词工作台</strong>
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
  color: #1d2433;
  background: #f4f6f8;
  font-family: "Microsoft YaHei", "PingFang SC", system-ui, sans-serif;
  font-synthesis: none;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  min-height: 100vh;
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
  gap: 10px;
  height: 48px;
  padding: 0 16px;
  flex: none;
  color: #fff;
  background: #202734;
}

.app-header strong {
  white-space: nowrap;
}

.app-nav {
  display: flex;
  align-self: stretch;
  align-items: center;
  gap: 4px;
  margin-left: auto;
}

.app-nav a {
  display: flex;
  height: 100%;
  align-items: center;
  padding: 0 14px;
  border-bottom: 2px solid transparent;
  color: #cbd1da;
  font-size: 14px;
  text-decoration: none;
}

.app-nav a:hover {
  color: #fff;
  background: rgb(255 255 255 / 6%);
}

.app-nav a.router-link-active {
  border-bottom-color: #79d3a5;
  color: #fff;
}

.brand-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 6px;
  color: #202734;
  background: #79d3a5;
  font-weight: 800;
}

@media (max-width: 560px) {
  .app-header {
    padding-right: 4px;
  }

  .app-header strong {
    overflow: hidden;
    text-overflow: ellipsis;
  }

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

