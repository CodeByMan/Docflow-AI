<script setup>
import { computed } from 'vue'
import AppIcon from './AppIcon.vue'
import StatusPill from './StatusPill.vue'
import { formatBytes, formatDate, titleCase } from '../utils/format'
import { downloadDocument } from '../services/api'

const props = defineProps({ document: Object })
const emit = defineEmits(['close', 'refresh', 'process', 'error'])

const result = computed(() => props.document?.result || null)
const statistics = computed(() => result.value?.statistics || {})
const entities = computed(() => result.value?.entities || {})
const domainResult = computed(() => result.value?.invoice || result.value?.contract || null)

async function downloadOriginal() {
  try {
    const blob = await downloadDocument(props.document.job_id)
    const url = URL.createObjectURL(blob)
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = props.document.filename
    anchor.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    emit('error', error.message || 'Unable to download the source document')
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="document" class="drawer-layer" @mousedown.self="emit('close')">
      <aside class="result-drawer" aria-label="Document details">
        <header class="drawer-header">
          <div>
            <span class="eyebrow">Processing result</span>
            <h2>{{ document.filename }}</h2>
          </div>
          <button class="icon-button" title="Close" @click="emit('close')">
            <AppIcon name="close" :size="20" />
          </button>
        </header>

        <div class="drawer-body">
          <div class="document-overview">
            <StatusPill :status="document.state" />
            <span>{{ formatBytes(document.size_bytes) }}</span>
            <span>{{ formatDate(document.created_at) }}</span>
          </div>

          <div v-if="document.error" class="notice notice--error">
            <strong>Processing failed</strong>
            <span>{{ document.error }}</span>
          </div>

          <div class="drawer-actions">
            <button class="button button--secondary" @click="downloadOriginal">
              <AppIcon name="download" :size="17" /> Download original
            </button>
            <button
              v-if="['uploaded', 'failed'].includes(document.state)"
              class="button button--primary"
              @click="emit('process', document)"
            >
              Process now
            </button>
            <button class="icon-button" title="Refresh status" @click="emit('refresh', document)">
              <AppIcon name="refresh" :size="18" />
            </button>
          </div>

          <template v-if="result">
            <section class="result-section result-section--highlight">
              <span class="eyebrow">Rule-based summary</span>
              <p>{{ result.summary || 'No summary was generated.' }}</p>
            </section>

            <section class="result-section">
              <div class="result-section__heading">
                <h3>Document analysis</h3>
                <span>{{ titleCase(result.document_type) }}</span>
              </div>
              <div class="mini-stat-grid">
                <div><strong>{{ statistics.words ?? 0 }}</strong><span>Words</span></div>
                <div><strong>{{ statistics.sentences ?? 0 }}</strong><span>Sentences</span></div>
                <div><strong>{{ statistics.paragraphs ?? 0 }}</strong><span>Paragraphs</span></div>
                <div><strong>{{ statistics.estimated_reading_minutes ?? 0 }}</strong><span>Min read</span></div>
              </div>
            </section>

            <section v-if="result.classification" class="result-section">
              <h3>Classification</h3>
              <dl class="details-list">
                <div><dt>Predicted type</dt><dd>{{ titleCase(result.classification.predicted_type) }}</dd></div>
                <div><dt>Confidence</dt><dd>{{ Math.round((result.classification.confidence || 0) * 100) }}%</dd></div>
                <div><dt>Requested</dt><dd>{{ titleCase(result.classification.requested_type) }}</dd></div>
              </dl>
            </section>

            <section v-if="domainResult" class="result-section">
              <h3>{{ titleCase(result.document_type) }} fields</h3>
              <dl class="details-list">
                <div v-for="(value, key) in domainResult" :key="key">
                  <dt>{{ titleCase(key) }}</dt>
                  <dd>{{ Array.isArray(value) ? (value.join(', ') || 'Not found') : (value ?? 'Not found') }}</dd>
                </div>
              </dl>
            </section>

            <section v-if="result.keywords?.length" class="result-section">
              <h3>Top keywords</h3>
              <div class="tag-list">
                <span v-for="keyword in result.keywords" :key="keyword.term">
                  {{ keyword.term }} <small>{{ keyword.count }}</small>
                </span>
              </div>
            </section>

            <section class="result-section">
              <h3>Extracted entities</h3>
              <div class="entity-groups">
                <div v-for="(items, group) in entities" :key="group">
                  <strong>{{ titleCase(group) }}</strong>
                  <span>{{ items?.length ? items.join(' · ') : 'None detected' }}</span>
                </div>
              </div>
            </section>

            <details class="json-details">
              <summary>View raw processing JSON</summary>
              <pre>{{ JSON.stringify(result, null, 2) }}</pre>
            </details>
          </template>

          <div v-else-if="['queued', 'processing'].includes(document.state)" class="processing-state">
            <span class="processing-orbit" />
            <strong>Analysis is running</strong>
            <p>This view updates automatically while the document is processed.</p>
          </div>
          <div v-else-if="document.state === 'uploaded'" class="processing-state">
            <AppIcon name="clock" :size="30" />
            <strong>Ready to process</strong>
            <p>The file is stored safely and waiting for processing.</p>
          </div>
        </div>
      </aside>
    </div>
  </Teleport>
</template>
