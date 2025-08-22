export async function onRequest(context) {
  const { params, request, env } = context;
  const url = new URL(request.url);
  // Sajikan /folder dengan query ?dir=...
  url.pathname = "/folder";
  url.search = `?dir=${encodeURIComponent(params.dir)}`;
  // Proxy ke asset statik tanpa mengubah URL di address bar:
  return env.ASSETS.fetch(new Request(url.toString(), request));
}
