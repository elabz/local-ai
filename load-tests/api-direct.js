/**
 * k6 Load Test: Direct LiteLLM API
 *
 * Tests the LiteLLM proxy directly, bypassing the HeartCode backend.
 * This measures raw LLM inference performance without backend overhead.
 *
 * Usage:
 *   k6 run -e API_KEY=hc-sk-xxx --vus 10 --duration 60s api-direct.js
 *
 * Environment Variables:
 *   API_KEY     - HeartCode API key (hc-sk-...) [required]
 *   API_URL     - LiteLLM URL (default: http://localhost:4000)
 *   MODEL       - Model to use (default: heartcode-chat-sfw)
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const requestSuccess = new Rate('request_success');
const ttfb = new Trend('time_to_first_byte', true);
const totalDuration = new Trend('total_duration', true);
const tokensGenerated = new Counter('tokens_generated');
const requestsSent = new Counter('requests_sent');

// Configuration
export const options = {
  stages: [
    { duration: '10s', target: 5 },    // Ramp up
    { duration: '2m', target: 10 },    // Sustain load
    { duration: '10s', target: 0 },    // Ramp down
  ],
  thresholds: {
    request_success: ['rate>0.95'],           // 95% success rate
    time_to_first_byte: ['p(95)<5000'],       // 95% TTFB under 5s
    total_duration: ['p(95)<30000'],          // 95% total under 30s
  },
};

const API_URL = __ENV.API_URL || 'http://localhost:4000';
const API_KEY = __ENV.API_KEY || '';
const MODEL = __ENV.MODEL || 'heartcode-chat-sfw';

// Test prompts - varied complexity
const TEST_PROMPTS = [
  { prompt: 'Hello! How are you?', expectedTokens: 20 },
  { prompt: 'Tell me a very short joke.', expectedTokens: 50 },
  { prompt: 'What is 2 + 2? Answer briefly.', expectedTokens: 10 },
  { prompt: 'Describe a sunset in one sentence.', expectedTokens: 30 },
  { prompt: 'Say something nice.', expectedTokens: 20 },
];

export function setup() {
  console.log(`Testing LiteLLM API at ${API_URL}`);
  console.log(`Model: ${MODEL}`);

  if (!API_KEY) {
    throw new Error('API_KEY environment variable required (hc-sk-...)');
  }

  // Verify API is accessible
  const healthRes = http.get(`${API_URL}/health`);
  if (healthRes.status !== 200) {
    console.warn(`Health check returned ${healthRes.status}, continuing anyway...`);
  }

  // Verify API key works
  const modelsRes = http.get(`${API_URL}/v1/models`, {
    headers: { 'Authorization': `Bearer ${API_KEY}` },
  });

  if (modelsRes.status !== 200) {
    throw new Error(`API key validation failed: ${modelsRes.status} - ${modelsRes.body}`);
  }

  const models = modelsRes.json('data');
  console.log(`Available models: ${models.map(m => m.id).join(', ')}`);

  return { startTime: Date.now() };
}

export default function () {
  const testCase = TEST_PROMPTS[Math.floor(Math.random() * TEST_PROMPTS.length)];

  const payload = JSON.stringify({
    model: MODEL,
    messages: [
      { role: 'user', content: testCase.prompt }
    ],
    max_tokens: 100,
    temperature: 0.7,
  });

  const params = {
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    timeout: '60s',
  };

  const startTime = Date.now();
  const response = http.post(`${API_URL}/v1/chat/completions`, payload, params);
  const endTime = Date.now();

  requestsSent.add(1);
  ttfb.add(response.timings.waiting);
  totalDuration.add(endTime - startTime);

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'has choices': (r) => {
      try {
        const body = r.json();
        return body.choices && body.choices.length > 0;
      } catch {
        return false;
      }
    },
    'has content': (r) => {
      try {
        const body = r.json();
        return body.choices[0].message.content.length > 0;
      } catch {
        return false;
      }
    },
  });

  requestSuccess.add(success ? 1 : 0);

  // Track tokens if successful
  if (response.status === 200) {
    try {
      const body = response.json();
      if (body.usage && body.usage.completion_tokens) {
        tokensGenerated.add(body.usage.completion_tokens);
      }
    } catch (e) {
      // Ignore JSON parse errors
    }
  } else {
    console.error(`Request failed: ${response.status} - ${response.body}`);
  }

  // Random sleep between requests (1-3 seconds)
  sleep(1 + Math.random() * 2);
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration.toFixed(1)} seconds`);
}

export function handleSummary(data) {
  const summary = {
    'Total Requests': data.metrics.requests_sent ? data.metrics.requests_sent.values.count : 0,
    'Success Rate': data.metrics.request_success ?
      `${(data.metrics.request_success.values.rate * 100).toFixed(1)}%` : 'N/A',
    'TTFB p95': data.metrics.time_to_first_byte ?
      `${data.metrics.time_to_first_byte.values['p(95)'].toFixed(0)}ms` : 'N/A',
    'Total Duration p95': data.metrics.total_duration ?
      `${data.metrics.total_duration.values['p(95)'].toFixed(0)}ms` : 'N/A',
    'Tokens Generated': data.metrics.tokens_generated ?
      data.metrics.tokens_generated.values.count : 0,
  };

  console.log('\n=== Direct API Load Test Summary ===');
  for (const [key, value] of Object.entries(summary)) {
    console.log(`  ${key}: ${value}`);
  }

  return {
    stdout: textSummary(data, { indent: '  ', enableColors: true }),
  };
}

// Import text summary helper
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';
