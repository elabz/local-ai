/**
 * k6 Load Test: Chat Streaming Endpoint
 *
 * Tests chat message sending and SSE streaming performance.
 * This is the most critical endpoint for user experience.
 *
 * Usage:
 *   k6 run --vus 10 --duration 60s chat.js
 *
 * Note: Requires TEST_TOKEN environment variable with valid JWT
 *   k6 run -e TEST_TOKEN=<jwt> --vus 10 chat.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const chatSuccess = new Rate('chat_success');
const chatDuration = new Trend('chat_time_to_first_byte');
const messagesSent = new Counter('messages_sent');

// Test configuration - lower VUs for chat due to LLM inference cost
export const options = {
  stages: [
    { duration: '20s', target: 3 },    // Ramp up slowly
    { duration: '2m', target: 5 },     // Conservative concurrent users
    { duration: '20s', target: 0 },    // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<120000'],  // 95% under 120s (LLM inference can be slow)
    chat_success: ['rate>0.80'],           // 80% success rate
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TEST_TOKEN = __ENV.TEST_TOKEN || '';

// Test messages
const TEST_MESSAGES = [
  'Hello! How are you today?',
  'Tell me about yourself.',
  'What do you like to do for fun?',
  'What is your favorite color?',
  'Can you tell me a short story?',
];

let conversationId = null;
let characterId = null;

export default function () {
  if (!TEST_TOKEN) {
    console.error('TEST_TOKEN environment variable required');
    return;
  }

  const headers = {
    'Authorization': `Bearer ${TEST_TOKEN}`,
    'Content-Type': 'application/json',
  };

  group('Chat Flow', function () {
    // Get or create conversation
    if (!conversationId) {
      // Get a character first
      const charRes = http.get(`${BASE_URL}/api/v1/characters?page_size=1`, { headers });
      if (charRes.status === 200 && charRes.json('items').length > 0) {
        characterId = charRes.json('items')[0].id;

        // Create conversation
        const convRes = http.post(
          `${BASE_URL}/api/v1/conversations`,
          JSON.stringify({ character_id: characterId }),
          { headers }
        );

        if (convRes.status === 201) {
          conversationId = convRes.json('id');
        }
      }
    }

    if (!conversationId) {
      console.error('Could not create conversation');
      return;
    }

    // Send a message
    const message = TEST_MESSAGES[Math.floor(Math.random() * TEST_MESSAGES.length)];
    const payload = JSON.stringify({ content: message });

    const chatStart = Date.now();

    // Note: k6 doesn't natively support SSE streaming well
    // We're testing the initial request latency here
    const chatRes = http.post(
      `${BASE_URL}/api/v1/chat/${conversationId}/stream`,
      payload,
      {
        headers,
        timeout: '120s',
      }
    );

    const ttfb = Date.now() - chatStart;
    chatDuration.add(ttfb);

    const chatOk = check(chatRes, {
      'chat response status ok': (r) => r.status === 200,
      'chat returns SSE': (r) => r.headers['Content-Type']?.includes('text/event-stream'),
    });

    chatSuccess.add(chatOk ? 1 : 0);
    messagesSent.add(1);
  });

  // Longer sleep between chat requests (LLM is expensive)
  sleep(3 + Math.random() * 2);
}

export function setup() {
  console.log(`Running chat load test against ${BASE_URL}`);

  if (!TEST_TOKEN) {
    throw new Error('TEST_TOKEN environment variable is required. Get a token by logging in.');
  }

  const healthRes = http.get(`${BASE_URL}/health`);
  if (healthRes.status !== 200) {
    throw new Error(`API health check failed: ${healthRes.status}`);
  }

  // Verify token is valid
  const meRes = http.get(`${BASE_URL}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${TEST_TOKEN}` },
  });
  if (meRes.status !== 200) {
    throw new Error('Invalid TEST_TOKEN - authentication failed');
  }

  console.log(`Authenticated as: ${meRes.json('email')}`);

  return { startTime: Date.now() };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration.toFixed(1)} seconds`);
  console.log(`Note: Clean up test conversations manually if needed`);
}
