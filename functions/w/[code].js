export async function onRequest(context) {
  const { params, request, env } = context;
  const url = new URL(request.url);
  url.pathname = "/watch";
  url.search = `?v=${encodeURIComponent(params.code)}`;
  return env.ASSETS.fetch(new Request(url.toString(), request));
}
