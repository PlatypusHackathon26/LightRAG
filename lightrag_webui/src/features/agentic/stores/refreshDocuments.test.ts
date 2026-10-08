import { describe, expect, test } from 'bun:test'
import { useAgenticStore } from './agenticStore'
import type { KnowledgeDocument } from '../types/agentic'

const doc = (id: string, indexStatus: KnowledgeDocument['indexStatus']): KnowledgeDocument => ({
  id, name: id, tags: [], sizeBytes: 1, importedAt: '', indexStatus,
})

describe('refreshDocuments', () => {
  test('replaces the list with the gateway one but keeps uploads still in progress', async () => {
    useAgenticStore.setState({ documents: [doc('doc-upload-1', 'parsing'), doc('doc-upload-2', 'vectorized'), doc('old', 'vectorized')] })
    await useAgenticStore.getState().refreshDocuments(async () => [doc('doc-real', 'vectorized')])
    expect(useAgenticStore.getState().documents.map((d) => d.id)).toEqual(['doc-upload-1', 'doc-real'])
  })
})
