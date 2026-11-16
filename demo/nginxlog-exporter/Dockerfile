FROM golang:1.27.3-alpine AS build
RUN apk add --no-cache git
WORKDIR /src
RUN git init . \
    && git remote add origin https://github.com/martin-helmich/prometheus-nginxlog-exporter.git \
    && git fetch --depth 1 origin 76552e7cadc1f76b4e28b5c872412db4a091aca0 \
    && git checkout --detach FETCH_HEAD
RUN go mod edit -require=golang.org/x/net@v0.62.0 \
    && go mod tidy \
    && CGO_ENABLED=0 go build -trimpath -buildvcs=false -o /out/prometheus-nginxlog-exporter .

FROM scratch
COPY --from=build /out/prometheus-nginxlog-exporter /prometheus-nginxlog-exporter
USER 10001:10001
ENTRYPOINT ["/prometheus-nginxlog-exporter"]
