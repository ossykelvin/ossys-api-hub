import { test } from 'node:test'
import assert from 'node:assert/strict'
import { connectionKey, inheritedApiKey, withApiKey } from './groupApiKey.ts'

const query = { group: 'Daylist', endpoint: 'https://api.example.com/auth/v1/token', headersText: '{"apikey":"public-key"}' }
test('inherits across paths, but never across groups, origins, protocols or ports', () => {
  assert.equal(inheritedApiKey('Daylist', 'https://api.example.com/rest/v1/tasks', [query]), 'public-key')
  for (const endpoint of ['https://other.example.com', 'http://api.example.com', 'https://api.example.com:8443']) {
    assert.equal(inheritedApiKey('Daylist', endpoint, [query]), '')
  }
  assert.equal(inheritedApiKey('Other', query.endpoint, [query]), '')
  assert.equal(connectionKey('Daylist', 'not a URL'), '')
})
test('ambiguous saved keys require explicit configuration; corrupt headers are ignored', () => {
  assert.equal(inheritedApiKey('Daylist', query.endpoint, [query, { ...query, headersText: '{"APIKEY":"other"}' }]), '')
  assert.equal(inheritedApiKey('Daylist', query.endpoint, [query, { ...query, headersText: 'null' }]), 'public-key')
})
test('explicit request header takes precedence case-insensitively', () => {
  assert.deepEqual(withApiKey({ APIKEY: 'override' }, 'shared'), { APIKEY: 'override' })
  assert.deepEqual(withApiKey({ Accept: 'application/json' }, 'shared'), { Accept: 'application/json', apikey: 'shared' })
  assert.deepEqual(withApiKey({}, ''), {})
})
