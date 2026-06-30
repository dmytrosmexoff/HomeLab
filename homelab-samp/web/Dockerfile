FROM node:20-alpine
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev
COPY server.js ./
COPY samp-query.js ./
COPY downloader.js ./
COPY public ./public
EXPOSE 3000
CMD ["node", "server.js"]
