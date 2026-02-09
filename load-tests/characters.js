/**
 * k6 Load Test: Character Browsing Endpoints
 *
 * Tests character listing, filtering, and detail views.
 *
 * Usage:
 *   k6 run --vus 50 --duration 60s characters.js
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const listSuccess = new Rate('character_list_success');
const listDuration = new Trend('character_list_duration');
const detailSuccess = new Rate('character_detail_success');

// Test configuration
export const options = {
  stages: [
    { duration: '20s', target: 30 },  // Ramp up
    { duration: '1m', target: 100 },  // Peak load
    { duration: '20s', target: 0 },   // Ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<300'],   // 95% under 300ms
    character_list_success: ['rate>0.99'],
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export default function () {
  group('Character Browsing', function () {
    // List characters (no auth required for public characters)
    const listStart = Date.now();
    const listRes = http.get(`${BASE_URL}/api/v1/characters?page=1&page_size=20`);
    const listTime = Date.now() - listStart;

    listDuration.add(listTime);

    const listOk = check(listRes, {
      'list status is 200': (r) => r.status === 200,
      'list has items': (r) => Array.isArray(r.json('items')),
      'list has pagination': (r) => r.json('total') !== undefined,
    });

    listSuccess.add(listOk ? 1 : 0);

    // If we got characters, try to get detail for one
    if (listOk && listRes.json('items').length > 0) {
      const characters = listRes.json('items');
      const randomChar = characters[Math.floor(Math.random() * characters.length)];

      const detailRes = http.get(`${BASE_URL}/api/v1/characters/${randomChar.id}`);

      const detailOk = check(detailRes, {
        'detail status is 200': (r) => r.status === 200,
        'detail has name': (r) => r.json('name') !== undefined,
        'detail has persona': (r) => r.json('persona') !== undefined,
      });

      detailSuccess.add(detailOk ? 1 : 0);
    }

    // Test search
    const searchRes = http.get(`${BASE_URL}/api/v1/characters?search=luna&page_size=10`);
    check(searchRes, {
      'search returns 200': (r) => r.status === 200,
    });

    // Test sorting
    const sortRes = http.get(`${BASE_URL}/api/v1/characters?sort=recent&page_size=10`);
    check(sortRes, {
      'sort returns 200': (r) => r.status === 200,
    });
  });

  sleep(0.5);
}

export function setup() {
  console.log(`Running character browsing load test against ${BASE_URL}`);

  const healthRes = http.get(`${BASE_URL}/health`);
  if (healthRes.status !== 200) {
    throw new Error(`API health check failed: ${healthRes.status}`);
  }

  // Verify characters exist
  const listRes = http.get(`${BASE_URL}/api/v1/characters?page_size=1`);
  if (listRes.json('total') === 0) {
    console.warn('No characters found - test may not be meaningful');
  }

  return { startTime: Date.now() };
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration.toFixed(1)} seconds`);
}
