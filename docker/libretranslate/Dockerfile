FROM libretranslate/libretranslate:latest

COPY --chmod=755 docker/libretranslate/import-models-entrypoint.sh /app/import-models-entrypoint.sh

ENTRYPOINT ["/app/import-models-entrypoint.sh"]
