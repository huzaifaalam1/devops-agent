# Local development only; not a production deployment image.
FROM node:20.9
WORKDIR /app
ENV NODE_ENV=development
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
RUN npm ci --include=dev --no-audit --no-fund
COPY . .
EXPOSE 3000
CMD ["npm", "run", "dev"]
