<script setup>
import { computed } from 'vue'

const props = defineProps({ status: { type: String, default: 'unknown' } })
const normalized = computed(() => props.status.toLowerCase())
</script>

<template>
  <span class="status-pill" :class="`status-pill--${normalized}`">
    <span class="status-pill__dot" />
    {{ normalized }}
  </span>
</template>
