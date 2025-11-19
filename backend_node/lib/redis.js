const { createClient } = require('redis');

let client;

async function initRedis() {
  client = createClient({ url: process.env.REDIS_URL });
  client.on('error', err => console.error('Redis Client Error', err));
  await client.connect();
}

function getRedis() {
  if (!client) throw new Error('Redis not initialized');
  return client;
}

module.exports = { initRedis, getRedis };
