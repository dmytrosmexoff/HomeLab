FROM node:20-bookworm-slim

WORKDIR /app

# npm зависимости ставятся автоматически при сборке образа
COPY package.json ./
RUN npm install --omit=dev

COPY . .

ENV PORT=2323
EXPOSE 2323

CMD ["node", "server.js"]
