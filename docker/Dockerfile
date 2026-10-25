FROM alpine:3.19

RUN apk add --no-cache openvpn iptables bash curl iproute2
RUN apk add --no-cache --repository=https://dl-cdn.alpinelinux.org/alpine/edge/testing microsocks

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 1080

ENTRYPOINT ["/entrypoint.sh"]
