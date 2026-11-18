FROM node:24-slim AS build
WORKDIR /web
ARG VITE_MLFLOW_URL=http://localhost:5000
ENV VITE_MLFLOW_URL=$VITE_MLFLOW_URL
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend ./
RUN npm run build
FROM nginx:1.28-alpine
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html
COPY docs /usr/share/nginx/html/docs
EXPOSE 80
