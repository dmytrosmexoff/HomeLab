'use strict';
const express = require('express');
const path = require('path');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const API_URL = process.env.API_URL || 'http://samp-monitor-api:3000';
const PORT = parseInt(process.env.PORT || '2323', 10);

const apiProxy = createProxyMiddleware({ target: API_URL, changeOrigin: true });
const wsProxy = createProxyMiddleware({ target: API_URL, changeOrigin: true, ws: true });

app.use('/api', apiProxy);
app.use('/ws', wsProxy);
app.use(express.static(path.join(__dirname, 'public')));

const server = app.listen(PORT, () => console.log('Веб-панель слушает порт ' + PORT));
server.on('upgrade', wsProxy.upgrade);
