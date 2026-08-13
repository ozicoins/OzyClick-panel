FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

RUN sed -i "s|/run/nginx.pid|/tmp/nginx.pid|g" /etc/nginx/nginx.conf \
 && sed -i "s|/var/run/nginx.pid|/tmp/nginx.pid|g" /etc/nginx/nginx.conf \
 && sed -i "/^user /d" /etc/nginx/nginx.conf \
 && touch /tmp/nginx.pid \
 && chown -R nginx:nginx /usr/share/nginx/html /var/cache/nginx /tmp/nginx.pid

USER nginx
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
