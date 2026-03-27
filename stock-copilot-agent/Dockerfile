FROM node:18-slim

WORKDIR /app

COPY package*.json ./
RUN npm ci --only=production

COPY lib/ lib/

EXPOSE 3978

CMD ["node", "lib/index.js"]
