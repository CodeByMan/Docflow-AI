<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import AppIcon from './components/AppIcon.vue'
import DocumentsTable from './components/DocumentsTable.vue'
import MetricCard from './components/MetricCard.vue'
import ResultDrawer from './components/ResultDrawer.vue'
import UploadPanel from './components/UploadPanel.vue'
import {
  clearAccessKey,
  getDocument,
  getMetrics,
  hasAccessKey,
  healthCheck,
  listDocuments,
  processDocument,
  setAccessKey,
  uploadDocument,
} from './services/api'

const documents = ref([])
const metrics = ref({ total: 0, uploaded: 0, queued: 0, processing: 0, completed: 0, failed: 0 })
const selected = ref(null)
const loading = ref(true)
const uploadBusy = ref(false)
const uploadProgress = ref(0)
const serviceOnline = ref(false)
const mobileNavOpen = ref(false)
const toast = ref(null)
const accessKeyDialogOpen = ref(false)
const accessKeyInput = ref('')
const accessKeyError = ref('')
const accessKeyStored = ref(hasAccessKey())
let pollTimer = null
let toastTimer = null

const activeJobs = computed(() => documents.value.filter((item) => ['queued', 'processing'].includes(item.state)))
const completionRate = computed(() => {
  if (!metrics.value.total) return '0%'
  return `${Math.round((metrics.value.completed / metrics.value.total) * 100)}%`
})

function notify(message, type = 'success') {
  toast.value = { message, type }
  clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 4500)
}

function requestAccessKey() {
  clearAccessKey()
  accessKeyStored.value = false
  accessKeyInput.value = ''
  accessKeyError.value = 'Enter the hosted access key to open document data.'
  accessKeyDialogOpen.value = true
}

async function loadDashboard({ quiet = false } = {}) {
  if (!quiet) loading.value = true
  try {
    const [health, metricResponse, documentResponse] = await Promise.all([
      healthCheck(),
      getMetrics(),
      listDocuments(),
    ])
    serviceOnline.value = Boolean(health?.success)
    metrics.value = metricResponse.data
    documents.value = documentResponse.data.items
    if (selected.value) {
      const refreshed = documents.value.find((item) => item.job_id === selected.value.job_id)
      if (refreshed) selected.value = refreshed
    }
    return true
  } catch (error) {
    serviceOnline.value = error.status === 401
    if (error.status === 401) {
      requestAccessKey()
    } else if (!quiet) {
      notify(error.message || 'Unable to reach the API', 'error')
    }
    return false
  } finally {
    loading.value = false
  }
}

async function submitAccessKey() {
  const key = accessKeyInput.value.trim()
  if (!key) {
    accessKeyError.value = 'The access key is required.'
    return
  }

  setAccessKey(key)
  accessKeyStored.value = true
  accessKeyError.value = ''
  accessKeyDialogOpen.value = false
  const accepted = await loadDashboard()
  if (!accepted) {
    accessKeyError.value = 'The key was rejected. Check it and try again.'
  }
}

async function forgetAccessKey() {
  clearAccessKey()
  accessKeyStored.value = false
  selected.value = null
  documents.value = []
  await loadDashboard()
}

async function handleUpload(payload) {
  uploadBusy.value = true
  uploadProgress.value = 0
  try {
    const response = await uploadDocument({
      ...payload,
      onProgress: (value) => { uploadProgress.value = value },
    })
    selected.value = response.data
    notify(response.message)
    await loadDashboard({ quiet: true })
  } catch (error) {
    if (error.status === 401) requestAccessKey()
    else notify(error.message || 'Document upload failed', 'error')
  } finally {
    uploadBusy.value = false
    uploadProgress.value = 0
  }
}

async function handleProcess(document) {
  try {
    await processDocument(document.job_id)
    notify('Document processing queued')
    const response = await getDocument(document.job_id)
    selected.value = response.data
    await loadDashboard({ quiet: true })
  } catch (error) {
    if (error.status === 401) requestAccessKey()
    else notify(error.message || 'Unable to start processing', 'error')
  }
}

async function refreshSelected(document = selected.value) {
  if (!document) return
  try {
    const response = await getDocument(document.job_id)
    selected.value = response.data
    await loadDashboard({ quiet: true })
  } catch (error) {
    if (error.status === 401) requestAccessKey()
    else notify(error.message || 'Unable to refresh document', 'error')
  }
}

function startPolling() {
  pollTimer = window.setInterval(() => {
    if (activeJobs.value.length || selected.value?.state === 'processing' || selected.value?.state === 'queued') {
      loadDashboard({ quiet: true })
    }
  }, 2500)
}

onMounted(async () => {
  await loadDashboard()
  startPolling()
})

onBeforeUnmount(() => {
  clearInterval(pollTimer)
  clearTimeout(toastTimer)
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <a class="brand" href="#top" aria-label="DocFlow-AI home">
        <span class="brand-mark"><AppIcon name="sparkles" :size="21" /></span>
        <span><strong>DocFlow-AI</strong><small>Deterministic document processing</small></span>
      </a>
      <nav :class="{ 'nav-links--open': mobileNavOpen }" class="nav-links">
        <a href="#dashboard" @click="mobileNavOpen = false">Dashboard</a>
        <a href="#documents" @click="mobileNavOpen = false">Documents</a>
        <a href="/api/docs" target="_blank" rel="noreferrer">API docs</a>
      </nav>
      <div class="topbar-actions">
        <button
          v-if="accessKeyStored"
          class="session-key-button"
          type="button"
          @click="forgetAccessKey"
        >
          Forget session key
        </button>
        <span class="service-status" :class="{ online: serviceOnline }">
          <i /> {{ serviceOnline ? 'API online' : 'API offline' }}
        </span>
        <button class="mobile-menu" @click="mobileNavOpen = !mobileNavOpen">
          <AppIcon :name="mobileNavOpen ? 'close' : 'menu'" :size="22" />
        </button>
      </div>
    </header>

    <main id="top">
      <section class="hero" id="dashboard">
        <div class="hero-copy">
          <span class="hero-kicker"><AppIcon name="activity" :size="16" /> Bounded document workflow</span>
          <h1>Transform documents into <em>structured results.</em></h1>
          <p>
            Upload invoices and contracts, extract real text, detect key entities, classify content,
            and review results from one responsive workspace.
          </p>
          <div class="hero-meta">
            <span>PDF · DOCX · XLSX · CSV · JSON · TXT</span>
            <span>Developed by Muhammad Ali Nawaz</span>
          </div>
        </div>
        <div class="hero-visual" aria-hidden="true">
          <div class="visual-card visual-card--back">
            <span /><span /><span /><span />
          </div>
          <div class="visual-card visual-card--front">
            <div class="visual-card__top"><i /><b>Contract.pdf</b><small>Completed</small></div>
            <div class="visual-card__line wide" /><div class="visual-card__line" />
            <div class="visual-card__stats"><i /><i /><i /></div>
          </div>
          <span class="floating-chip floating-chip--one">12 entities</span>
          <span class="floating-chip floating-chip--two">94% confidence</span>
        </div>
      </section>

      <section class="metrics-grid" aria-label="Processing metrics">
        <MetricCard label="Total documents" :value="metrics.total" note="All uploaded jobs" icon="file" />
        <MetricCard label="In progress" :value="metrics.processing + metrics.queued" note="Queued or processing" icon="activity" tone="blue" />
        <MetricCard label="Completed" :value="metrics.completed" :note="`${completionRate} completion rate`" icon="check" tone="green" />
        <MetricCard label="Needs attention" :value="metrics.failed" note="Failed processing jobs" icon="error" tone="red" />
      </section>

      <section class="workspace-grid">
        <UploadPanel
          :busy="uploadBusy"
          :progress="uploadProgress"
          @upload="handleUpload"
        />
        <aside class="panel capability-panel">
          <span class="eyebrow">What happens next</span>
          <h2>From upload to insight</h2>
          <ol class="process-list">
            <li><span>01</span><div><strong>Secure intake</strong><p>Type and size validation, safe filenames, SHA-256 fingerprinting.</p></div></li>
            <li><span>02</span><div><strong>Real extraction</strong><p>Text, tables, spreadsheet rows, PDF pages, and document metadata.</p></div></li>
            <li><span>03</span><div><strong>Rule-based analysis</strong><p>Deterministic classification, summary, entities, keywords, invoice and contract fields.</p></div></li>
            <li><span>04</span><div><strong>Structured output</strong><p>Searchable history, downloadable source, and reusable JSON result.</p></div></li>
          </ol>
          <div class="privacy-note"><AppIcon name="check" :size="17" /><span><strong>Local-first processing</strong>No external AI service or model required.</span></div>
        </aside>
      </section>

      <div id="documents">
        <DocumentsTable
          :documents="documents"
          :loading="loading"
          @select="selected = $event"
          @refresh="loadDashboard()"
          @process="handleProcess"
        />
      </div>
    </main>

    <footer>
      <span>DocFlow-AI</span>
      <span>Developed by <strong>Muhammad Ali Nawaz</strong> · 2026</span>
    </footer>

    <ResultDrawer
      :document="selected"
      @close="selected = null"
      @refresh="refreshSelected"
      @process="handleProcess"
      @error="notify($event, 'error')"
    />

    <div v-if="accessKeyDialogOpen" class="access-key-layer">
      <form class="access-key-dialog" @submit.prevent="submitAccessKey">
        <span class="eyebrow">Hosted access</span>
        <h2>Enter your session key</h2>
        <p>
          The key is sent only to the API and retained in this browser tab's session storage.
          It is never compiled into the frontend bundle.
        </p>
        <label class="field">
          <span>Access key</span>
          <input
            v-model="accessKeyInput"
            type="password"
            autocomplete="off"
            spellcheck="false"
            autofocus
          />
        </label>
        <p v-if="accessKeyError" class="field-error">{{ accessKeyError }}</p>
        <button class="button button--primary button--full" type="submit">
          Unlock document workspace
        </button>
      </form>
    </div>

    <Transition name="toast">
      <div v-if="toast" class="toast-message" :class="`toast-message--${toast.type}`" role="status">
        <AppIcon :name="toast.type === 'error' ? 'error' : 'check'" :size="18" />
        {{ toast.message }}
      </div>
    </Transition>
  </div>
</template>
