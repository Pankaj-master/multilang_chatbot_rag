require('dotenv').config();
const express = require('express');
const cors = require('cors');

function resolveMiddleware(mod, name) {
  if (!mod) {
    console.warn(`resolveMiddleware: ${name} is falsy`);
    return null;
  }
  if (typeof mod === 'function') {
    console.log(`resolveMiddleware: ${name} is a function (middleware/router)`);
    return mod;
  }
  if (mod && mod.__esModule && mod.default) {
    console.log(`resolveMiddleware: ${name} is an ES module with default export`);
    return mod.default;
  }
  if (mod && mod.router && typeof mod.router === 'function') {
    console.log(`resolveMiddleware: ${name} has .router`);
    return mod.router;
  }
  // if it's an object that looks like an Express router, try it
  const keys = Object.keys(mod).slice(0, 10);
  console.log(`resolveMiddleware: ${name} is type=${typeof mod} keys=${JSON.stringify(keys)}`);
  return mod;
}

const { initDb } = require('./lib/db');
const { initRedis } = require('./lib/redis');

let rawHealth, rawChat;
try {
  rawHealth = require('./routes/health');
} catch (e) {
  console.error('Failed to require ./routes/health', e);
  rawHealth = null;
}
try {
  rawChat = require('./routes/chat');
} catch (e) {
  console.error('Failed to require ./routes/chat', e);
  rawChat = null;
}

const healthRouter = resolveMiddleware(rawHealth, 'health');
const chatRouter = resolveMiddleware(rawChat, 'chat');

const app = express();
app.use(cors());
app.use(express.json());

if (healthRouter) app.use('/health', healthRouter);
else app.get('/health', (req, res) => res.json({ ok: true, env: process.env.NODE_ENV || 'development', note: 'health router missing' }));

if (chatRouter) app.use('/api/chat', chatRouter);
else app.post('/api/chat', (req, res) => res.status(500).json({ error: 'chat router missing' }));

const port = process.env.PORT || 8001;

async function start() {
  try {
    await initDb();
  } catch (e) {
    console.error('Failed to init DB', e);
    process.exit(1);
  }
  try {
    await initRedis();
  } catch (e) {
    console.error('Failed to init Redis', e);
    process.exit(1);
  }

  app.listen(port, () => {
    console.log(`Node backend listening on ${port}`);
  });
}

start().catch(err => {
  console.error('Failed to start node backend error:', err);
  process.exit(1);
});
