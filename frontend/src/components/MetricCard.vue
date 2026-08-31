<script setup>
import AppIcon from './AppIcon.vue'

defineProps({
  label: String,
  value: [String, Number],
  note: String,
  icon: String,
  tone: { type: String, default: 'neutral' },
})
</script>

<template>
  <article class="metric-card" :class="`metric-card--${tone}`">
    <div class="metric-card__icon"><AppIcon :name="icon" :size="22" /></div>
    <div>
      <p class="metric-card__label">{{ label }}</p>
      <strong class="metric-card__value">{{ value }}</strong>
      <span class="metric-card__note">{{ note }}</span>
    </div>
  </article>
</template>
