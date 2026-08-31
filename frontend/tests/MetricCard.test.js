import { renderToString } from '@vue/server-renderer'
import { createSSRApp } from 'vue'
import { describe, expect, it } from 'vitest'
import MetricCard from '../src/components/MetricCard.vue'

describe('MetricCard', () => {
  it('renders metric content', async () => {
    const app = createSSRApp(MetricCard, {
      label: 'Completed',
      value: 12,
      note: 'All good',
      icon: 'check',
    })
    const html = await renderToString(app)
    expect(html).toContain('Completed')
    expect(html).toContain('12')
    expect(html).toContain('All good')
  })
})
