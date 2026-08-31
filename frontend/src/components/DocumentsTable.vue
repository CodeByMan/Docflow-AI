<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import StatusPill from './StatusPill.vue'
import { formatBytes, formatDate } from '../utils/format'

const props = defineProps({
  documents: { type: Array, default: () => [] },
  loading: Boolean,
})
const emit = defineEmits(['select', 'refresh', 'process'])
const query = ref('')

const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return props.documents
  return props.documents.filter((document) =>
    [document.filename, document.job_id, document.requested_type, document.state]
      .join(' ')
      .toLowerCase()
      .includes(needle),
  )
})
</script>

<template>
  <section class="panel documents-panel">
    <div class="panel-heading panel-heading--table">
      <div>
        <span class="eyebrow">Processing history</span>
        <h2>Recent documents</h2>
      </div>
      <div class="table-actions">
        <label class="search-field">
          <AppIcon name="search" :size="17" />
          <input v-model="query" type="search" placeholder="Search documents" />
        </label>
        <button class="icon-button" title="Refresh" :disabled="loading" @click="emit('refresh')">
          <AppIcon name="refresh" :size="18" />
        </button>
      </div>
    </div>

    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Document</th>
            <th>Type</th>
            <th>Status</th>
            <th>Uploaded</th>
            <th><span class="sr-only">Actions</span></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading && !documents.length">
            <td colspan="5"><div class="skeleton-row" /></td>
          </tr>
          <tr v-else-if="!filtered.length">
            <td colspan="5">
              <div class="empty-state">
                <AppIcon name="file" :size="28" />
                <strong>No documents found</strong>
                <span>Your processed documents will appear here.</span>
              </div>
            </td>
          </tr>
          <tr
            v-for="document in filtered"
            :key="document.job_id"
            class="clickable-row"
            @click="emit('select', document)"
          >
            <td>
              <div class="document-cell">
                <span class="file-badge">{{ document.extension?.replace('.', '').toUpperCase() }}</span>
                <span>
                  <strong>{{ document.filename }}</strong>
                  <small>{{ formatBytes(document.size_bytes) }}</small>
                </span>
              </div>
            </td>
            <td><span class="muted-capitalized">{{ document.requested_type }}</span></td>
            <td><StatusPill :status="document.state" /></td>
            <td><span class="muted-text">{{ formatDate(document.created_at) }}</span></td>
            <td>
              <button
                v-if="['uploaded', 'failed'].includes(document.state)"
                class="text-button"
                @click.stop="emit('process', document)"
              >
                Process
              </button>
              <button v-else class="row-arrow" title="View details" @click.stop="emit('select', document)">
                <AppIcon name="arrow" :size="18" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
