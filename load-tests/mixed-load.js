/**
 * k6 Load Test: Mixed User Behavior
 *
 * Simulates realistic user behavior patterns with a mix of:
 * - Browsing characters (60%)
 * - Authentication (20%)
 * - Chat interactions (20%)
 *
 * Usage:
 *   k6 run --vus 100 --duration 5m mixed-load.js
 *
 * For authenticated tests:
 *   k6 run -e TEST_TOKEN=<jwt> --vus 100 mixed-load.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const requestSuccess = new Rate('request_success');
const errorCount = new Counter('errors');

// Test configuration
export const options = {
  scenarios: {
    // Browsing scenario - highest load
    browsing: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: 50 },
        { duration: '3m', target: 100 },
        { duration: '30s', target: 0 },
      ],
      gracefulRampDown: '30s',
    },
    // Auth scenario - moderate load
    auth: {
      executor: 'constant-vus',
      vus: 10,
      duration: '4m',
      startTime: '30s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<1000', 'p(99)<2000'],
    request_success: ['rate>0.95'],
    errors: ['count<100'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const TEST_TOKEN = __ENV.TEST_TOKEN || '';

// Browser user behavior
function browserUser() {
  group('Browse Characters', function () {
    // View character list
    const listRes = http.get(`${BASE_URL}/api/v1/characters?page=1&page_size=20`);
    const listOk = check(listRes, {
      'list status 200': (r) => r.status === 200,
    });
    requestSuccess.add(listOk ? 1 : 0);
    if (!listOk) errorCount.add(1);

    sleep(0.5 + Math.random());

    // View character details
    if (listOk && listRes.json('items')?.length > 0) {
      const chars = listRes.json('items');
      const char = chars[Math.floor(Math.random() * chars.length)];

      const detailRes = http.get(`${BASE_URL}/api/v1/characters/${char.id}`);
      const detailOk = check(detailRes, {
        'detail status 200': (r) => r.status === 200,
      });
      requestSuccess.add(detailOk ? 1 : 0);
      if (!detailOk) errorCount.add(1);
    }

    sleep(1 + Math.random() * 2);

    // Search
    const searches = ['luna', 'ai', 'chat', 'friend'];
    const searchTerm = searches[Math.floor(Math.random() * searches.length)];
    const searchRes = http.get(`${BASE_URL}/api/v1/characters?search=${searchTerm}`);
    const searchOk = check(searchRes, {
      'search status 200': (r) => r.status === 200,
    });
    requestSuccess.add(searchOk ? 1 : 0);
    if (!searchOk) errorCount.add(1);

    sleep(1 + Math.random() * 2);

    // Pagination
    const page = Math.floor(Math.random() * 3) + 1;
    const pageRes = http.get(`${BASE_URL}/api/v1/characters?page=${page}`);
    check(pageRes, {
      'pagination status 200': (r) => r.status === 200,
    });
  });
}

// Authenticated user behavior
function authUser() {
  if (!TEST_TOKEN) return;

  const headers = {
    'Authorization': `Bearer ${TEST_TOKEN}`,
    'Content-Type': 'application/json',
  };

  group('Authenticated Actions', function () {
    // Get user profile
    const meRes = http.get(`${BASE_URL}/api/v1/auth/me`, { headers });
    const meOk = check(meRes, {
      'me status 200': (r) => r.status === 200,
    });
    requestSuccess.add(meOk ? 1 : 0);

    sleep(0.5);

    // Get conversations list
    const convRes = http.get(`${BASE_URL}/api/v1/conversations`, { headers });
    check(convRes, {
      'conversations status 200': (r) => r.status === 200,
    });

    sleep(1);

    // Get user settings
    const settingsRes = http.get(`${BASE_URL}/api/v1/settings`, { headers });
    check(settingsRes, {
      'settings status 200 or 404': (r) => r.status === 200 || r.status === 404,
    });
  });
}

export default function () {
  // 70% browsing, 30% authenticated
  if (Math.random() < 0.7) {
    browserUser();
  } else if (TEST_TOKEN) {
    authUser();
  } else {
    browserUser();
  }

  sleep(1 + Math.random() * 2);
}

export function setup() {
  console.log(`Running mixed load test against ${BASE_URL}`);
  console.log(`Test token provided: ${TEST_TOKEN ? 'Yes' : 'No'}`);

  const healthRes = http.get(`${BASE_URL}/health`);
  if (healthRes.status !== 200) {
    throw new Error(`API health check failed: ${healthRes.status}`);
  }

  return { startTime: Date.now() };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration.toFixed(1)} seconds`);
}

// Summary output
export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'load-test-summary.json': JSON.stringify(data),
  };
}

function textSummary(data, options) {
  const { metrics } = data;
  let output = '\n';
  output += '='.repeat(60) + '\n';
  output += '  HeartCode Load Test Summary\n';
  output += '='.repeat(60) + '\n\n';

  output += `  Total Requests:     ${metrics.http_reqs?.values?.count || 0}\n`;
  output += `  Success Rate:       ${((metrics.request_success?.values?.rate || 0) * 100).toFixed(2)}%\n`;
  output += `  Avg Response Time:  ${(metrics.http_req_duration?.values?.avg || 0).toFixed(2)}ms\n`;
  output += `  P95 Response Time:  ${(metrics.http_req_duration?.values?.['p(95)'] || 0).toFixed(2)}ms\n`;
  output += `  P99 Response Time:  ${(metrics.http_req_duration?.values?.['p(99)'] || 0).toFixed(2)}ms\n`;
  output += `  Errors:             ${metrics.errors?.values?.count || 0}\n`;

  output += '\n' + '='.repeat(60) + '\n';

  return output;
}
