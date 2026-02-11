/**
 * k6 Stress Test: All 8 GPUs (SFW + NSFW)
 *
 * Tests both model types to distribute load across all GPUs:
 * - GPUs 1-4: heartcode-chat-sfw
 * - GPUs 5-8: heartcode-chat-nsfw
 *
 * Features:
 * - Pre-test health check of all GPUs
 * - Periodic health checks during test
 * - Failure detection and reporting
 * - Both model types tested
 *
 * Usage:
 *   k6 run -e API_KEY=hc-sk-xxx --vus 10 --duration 30m stress-all-gpus.js
 *
 * Environment Variables:
 *   API_KEY     - HeartCode API key (hc-sk-...) [required]
 *   API_URL     - LiteLLM URL (default: http://localhost:4000)
 *   GPU_SERVER  - GPU server IP for health checks (default: 192.168.0.145)
 */

import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter, Gauge } from 'k6/metrics';

// Custom metrics
const requestSuccess = new Rate('request_success');
const sfwSuccess = new Rate('sfw_success');
const nsfwSuccess = new Rate('nsfw_success');
const responseTime = new Trend('response_time', true);
const tokensGenerated = new Counter('tokens_generated');
const gpuHealthy = new Gauge('gpu_healthy_count');
const failedRequests = new Counter('failed_requests');

// Configuration
export const options = {
  stages: [
    { duration: '1m', target: 16 },     // Ramp up to saturate all 8 GPUs (2 per GPU)
    { duration: '58m', target: 16 },    // Sustain load for 1 hour
    { duration: '1m', target: 0 },      // Ramp down
  ],
  thresholds: {
    request_success: ['rate>0.95'],     // 95% success rate
    response_time: ['p(95)<60000'],     // 95% under 60s
    sfw_success: ['rate>0.90'],         // 90% SFW success
    nsfw_success: ['rate>0.90'],        // 90% NSFW success
  },
};

const API_URL = __ENV.API_URL || 'http://localhost:4000';
const API_KEY = __ENV.API_KEY || '';
const GPU_SERVER = __ENV.GPU_SERVER || '192.168.0.145';

// GPU ports
const SFW_PORTS = [8080, 8081, 8082, 8083];
const NSFW_PORTS = [8084, 8085, 8086, 8087];

// Test prompts - ~500 tokens each to test realistic load
const TEST_PROMPTS = [
  `You are a helpful AI assistant. I would like you to provide detailed, comprehensive responses to my questions.
Please be thorough and include multiple perspectives when relevant. Consider both common knowledge and nuanced viewpoints.
Your responses should be well-structured with clear explanations.

Here is my question: Tell me about the history of artificial intelligence and machine learning.
Include key milestones, important figures, major breakthroughs, and how the field has evolved over time.
Discuss both the theoretical foundations and practical applications that have emerged.
What are the current challenges and future directions for AI research?`,

  `I'm interested in learning about climate change and environmental science. Please provide a detailed explanation
that covers the scientific evidence, causes, and potential solutions. Discuss the role of greenhouse gases,
the carbon cycle, and how human activities impact the climate system.
Include information about renewable energy sources, conservation strategies, and policy approaches that
different countries are taking to address climate change. What are the most impactful actions individuals
and organizations can take to reduce their carbon footprint?`,

  `Explain the concept of quantum mechanics and how it differs from classical physics.
Start with the basics and build up to more complex ideas. Discuss key principles like superposition,
entanglement, and wave-particle duality. Explain how quantum mechanics has led to practical applications
like quantum computing and quantum cryptography. What are some of the open questions and challenges
in quantum physics research today? How might quantum technology change society in the future?`,

  `Tell me about the fascinating world of marine biology and ocean ecosystems.
Describe the different zones of the ocean and the diverse life forms that inhabit each zone.
Discuss coral reefs, deep sea hydrothermal vents, and other unique environments.
Explain the food chains and energy flow in ocean ecosystems. What threats do marine ecosystems face,
and what conservation efforts are underway? How do ocean health and human well-being interconnect?`,

  `I'd like to understand the principles of economics and how modern economies function.
Explain concepts like supply and demand, market equilibrium, inflation, and monetary policy.
Discuss different economic systems and approaches, including capitalism, socialism, and mixed economies.
What role do central banks play in managing economies? How do international trade and finance work?
What are current economic challenges facing the world today?`,
];


// Check individual GPU health
function checkGpuHealth(port) {
  try {
    const res = http.get(`http://${GPU_SERVER}:${port}/health`, {
      timeout: '5s',
    });
    if (res.status === 200) {
      const body = JSON.parse(res.body);
      return body.status === 'healthy';
    }
    return false;
  } catch (e) {
    return false;
  }
}

// Check all GPUs and return count of healthy ones
function checkAllGpus() {
  let healthyCount = 0;
  const allPorts = [...SFW_PORTS, ...NSFW_PORTS];

  for (const port of allPorts) {
    if (checkGpuHealth(port)) {
      healthyCount++;
    }
  }

  return healthyCount;
}

// Report GPU health status
function reportGpuHealth() {
  console.log('GPU Health Check:');

  console.log('  SFW GPUs (1-4):');
  for (let i = 0; i < SFW_PORTS.length; i++) {
    const port = SFW_PORTS[i];
    const healthy = checkGpuHealth(port);
    console.log(`    GPU ${i + 1} (port ${port}): ${healthy ? 'HEALTHY' : 'UNHEALTHY'}`);
  }

  console.log('  NSFW GPUs (5-8):');
  for (let i = 0; i < NSFW_PORTS.length; i++) {
    const port = NSFW_PORTS[i];
    const healthy = checkGpuHealth(port);
    console.log(`    GPU ${i + 5} (port ${port}): ${healthy ? 'HEALTHY' : 'UNHEALTHY'}`);
  }
}

export function setup() {
  console.log(`\n=== Stress Test: All 8 GPUs ===`);
  console.log(`API URL: ${API_URL}`);
  console.log(`GPU Server: ${GPU_SERVER}`);
  console.log('');

  if (!API_KEY) {
    throw new Error('API_KEY environment variable required (hc-sk-...)');
  }

  // Check all GPUs before starting
  reportGpuHealth();

  const healthyCount = checkAllGpus();
  console.log(`\nHealthy GPUs: ${healthyCount}/8`);

  if (healthyCount < 8) {
    console.log('WARNING: Not all GPUs are healthy! Test will continue but may have failures.');
  }

  if (healthyCount === 0) {
    throw new Error('No healthy GPUs found! Cannot run test.');
  }

  // Verify API key works
  const modelsRes = http.get(`${API_URL}/v1/models`, {
    headers: { 'Authorization': `Bearer ${API_KEY}` },
  });

  if (modelsRes.status !== 200) {
    throw new Error(`API key validation failed: ${modelsRes.status}`);
  }

  console.log('\nStarting stress test...\n');

  return {
    startTime: Date.now(),
    initialHealthy: healthyCount,
  };
}

export default function (data) {
  // Alternate between SFW and NSFW models to distribute load
  const useSfw = Math.random() > 0.5;
  const model = useSfw ? 'heartcode-chat-sfw' : 'heartcode-chat-nsfw';
  const prompt = TEST_PROMPTS[Math.floor(Math.random() * TEST_PROMPTS.length)];

  const payload = JSON.stringify({
    model: model,
    messages: [{ role: 'user', content: prompt }],
    max_tokens: 2048, // Extended response length for stress testing
    temperature: 0.7,
  });

  const params = {
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    timeout: '90s',
  };

  const startTime = Date.now();
  const response = http.post(`${API_URL}/v1/chat/completions`, payload, params);
  const duration = Date.now() - startTime;

  responseTime.add(duration);

  const success = check(response, {
    'status is 200': (r) => r.status === 200,
    'has content': (r) => {
      try {
        const body = r.json();
        return body.choices && body.choices[0].message.content.length > 0;
      } catch {
        return false;
      }
    },
  });

  requestSuccess.add(success ? 1 : 0);

  if (useSfw) {
    sfwSuccess.add(success ? 1 : 0);
  } else {
    nsfwSuccess.add(success ? 1 : 0);
  }

  if (!success) {
    failedRequests.add(1);
    console.log(`FAILED: ${model} - Status: ${response.status} - ${response.body?.substring(0, 100)}`);
  }

  // Track tokens if successful
  if (response.status === 200) {
    try {
      const body = response.json();
      if (body.usage && body.usage.completion_tokens) {
        tokensGenerated.add(body.usage.completion_tokens);
      }
    } catch (e) {
      // Ignore parse errors
    }
  }

  // Periodic health check (every ~50 iterations per VU)
  if (Math.random() < 0.02) {
    const healthyCount = checkAllGpus();
    gpuHealthy.add(healthyCount);

    if (healthyCount < 8) {
      console.log(`WARNING: Only ${healthyCount}/8 GPUs healthy!`);
    }
  }

  // Random sleep between requests (1-3 seconds)
  sleep(1 + Math.random() * 2);
}

export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;

  console.log(`\n=== Test Complete ===`);
  console.log(`Duration: ${(duration / 60).toFixed(1)} minutes`);
  console.log(`Initial healthy GPUs: ${data.initialHealthy}/8`);

  // Final health check
  console.log('\nFinal GPU Health:');
  reportGpuHealth();

  const finalHealthy = checkAllGpus();
  console.log(`\nFinal healthy GPUs: ${finalHealthy}/8`);

  if (finalHealthy < data.initialHealthy) {
    console.log(`\n⚠️  WARNING: ${data.initialHealthy - finalHealthy} GPU(s) became unhealthy during the test!`);
  }
}

export function handleSummary(data) {
  const metrics = data.metrics;

  console.log('\n=== STRESS TEST SUMMARY ===');
  console.log(`Total Requests: ${metrics.http_reqs?.values?.count || 0}`);
  console.log(`Success Rate: ${((metrics.request_success?.values?.rate || 0) * 100).toFixed(1)}%`);
  console.log(`SFW Success: ${((metrics.sfw_success?.values?.rate || 0) * 100).toFixed(1)}%`);
  console.log(`NSFW Success: ${((metrics.nsfw_success?.values?.rate || 0) * 100).toFixed(1)}%`);
  console.log(`Failed Requests: ${metrics.failed_requests?.values?.count || 0}`);
  console.log(`Response Time p95: ${(metrics.response_time?.values?.['p(95)'] || 0).toFixed(0)}ms`);
  console.log(`Tokens Generated: ${metrics.tokens_generated?.values?.count || 0}`);

  return {
    stdout: textSummary(data, { indent: '  ', enableColors: true }),
  };
}

import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';
