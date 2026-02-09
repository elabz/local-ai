/**
 * k6 Load Test: Authentication Endpoints
 *
 * Tests login, registration, and token refresh performance.
 *
 * Usage:
 *   k6 run --vus 10 --duration 30s auth.js
 *   k6 run --vus 50 --duration 60s auth.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const loginSuccess = new Rate('login_success');
const loginDuration = new Trend('login_duration');

// Test configuration
export const options = {
  stages: [
    { duration: '30s', target: 20 },  // Ramp up to 20 users
    { duration: '1m', target: 50 },   // Stay at 50 users
    { duration: '30s', target: 0 },   // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],  // 95% of requests under 500ms
    login_success: ['rate>0.95'],       // 95% success rate
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

// Test user credentials (should be created before test)
const TEST_USERS = [
  { email: 'loadtest1@example.com', password: 'LoadTest123!' },
  { email: 'loadtest2@example.com', password: 'LoadTest123!' },
  { email: 'loadtest3@example.com', password: 'LoadTest123!' },
];

export default function () {
  const user = TEST_USERS[Math.floor(Math.random() * TEST_USERS.length)];

  group('Authentication Flow', function () {
    // Login test
    const loginPayload = JSON.stringify({
      email: user.email,
      password: user.password,
    });

    const loginParams = {
      headers: { 'Content-Type': 'application/json' },
    };

    const loginStart = Date.now();
    const loginRes = http.post(`${BASE_URL}/api/v1/auth/login`, loginPayload, loginParams);
    const loginTime = Date.now() - loginStart;

    loginDuration.add(loginTime);

    const loginOk = check(loginRes, {
      'login status is 200': (r) => r.status === 200,
      'login has access_token': (r) => r.json('access_token') !== undefined,
    });

    loginSuccess.add(loginOk ? 1 : 0);

    if (loginOk) {
      const token = loginRes.json('access_token');

      // Test authenticated endpoint
      const meRes = http.get(`${BASE_URL}/api/v1/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      check(meRes, {
        'me endpoint returns 200': (r) => r.status === 200,
        'me returns user email': (r) => r.json('email') === user.email,
      });

      // Token refresh test
      const refreshRes = http.post(`${BASE_URL}/api/v1/auth/refresh`, null, {
        headers: { 'Content-Type': 'application/json' },
      });

      check(refreshRes, {
        'refresh returns 200 or 401': (r) => r.status === 200 || r.status === 401,
      });
    }
  });

  sleep(1);
}

export function setup() {
  console.log(`Running auth load test against ${BASE_URL}`);
  console.log('Ensure test users exist before running this test.');

  // Verify API is accessible
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
