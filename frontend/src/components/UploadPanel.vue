<script setup>
import { computed, ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { formatBytes } from '../utils/format'

const emit = defineEmits(['upload'])

const file = ref(null)
const documentType = ref('auto')
const autoProcess = ref(true)
const dragActive = ref(false)

const props = defineProps({
  busy: Boolean,
  progress: { type: Number, default: 0 },
})

const canUpload = computed(() => Boolean(file.value) && !props.busy)

function pickFile(event) {
  const selected = event.target.files?.[0]
  if (selected) file.value = selected
}

function handleDrop(event) {
  dragActive.value = false
  const selected = event.dataTransfer?.files?.[0]
  if (selected) file.value = selected
}

function submitFile() {
  if (!canUpload.value) return
  emit('upload', {
    file: file.value,
    documentType: documentType.value,
    autoProcess: autoProcess.value,
  })
}

</script>

<template>
  <section class="panel upload-panel">
    <div class="panel-heading">
      <div>
        <span class="eyebrow">New processing job</span>
        <h2>Upload and analyze</h2>
      </div>
    </div>

    <div class="upload-flow">
      <label
        class="drop-zone"
        :class="{ 'drop-zone--active': dragActive, 'drop-zone--selected': file }"
        @dragover.prevent="dragActive = true"
        @dragleave.prevent="dragActive = false"
        @drop.prevent="handleDrop"
      >
        <input
          type="file"
          accept=".pdf,.docx,.txt,.md,.csv,.json,.xlsx"
          :disabled="busy"
          @change="pickFile"
        />
        <div class="drop-zone__icon"><AppIcon :name="file ? 'check' : 'upload'" :size="28" /></div>
        <template v-if="file">
          <strong>{{ file.name }}</strong>
          <span>{{ formatBytes(file.size) }} · Click or drop to replace</span>
        </template>
        <template v-else>
          <strong>Drop a document here</strong>
          <span>PDF, DOCX, TXT, MD, CSV, JSON or XLSX · maximum 10 MB</span>
        </template>
      </label>

      <div class="form-grid">
        <label class="field">
          <span>Document type</span>
          <select v-model="documentType" :disabled="busy">
            <option value="auto">Auto detect</option>
            <option value="invoice">Invoice</option>
            <option value="contract">Contract</option>
          </select>
        </label>
        <label class="toggle-field">
          <span>
            <strong>Process immediately</strong>
            <small>Start analysis after upload</small>
          </span>
          <input v-model="autoProcess" type="checkbox" :disabled="busy" />
          <i aria-hidden="true" />
        </label>
      </div>

      <div v-if="busy" class="progress-track" aria-live="polite">
        <div class="progress-track__bar" :style="{ width: `${Math.max(progress, 4)}%` }" />
        <span>{{ progress < 100 ? `Uploading ${progress}%` : 'Preparing analysis…' }}</span>
      </div>

      <button class="button button--primary button--full" :disabled="!canUpload" @click="submitFile">
        <AppIcon name="sparkles" :size="18" />
        {{ busy ? 'Working…' : 'Analyze document' }}
      </button>
    </div>

  </section>
</template>
