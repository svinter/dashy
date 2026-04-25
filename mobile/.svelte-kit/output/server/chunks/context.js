import "clsx";
import "@sveltejs/kit/internal";
import "./exports.js";
import "./utils.js";
import "@sveltejs/kit/internal/server";
import "./root.js";
import "./state.svelte.js";
import { l as setContext, j as getContext } from "./renderer.js";
import { r as readable } from "./index.js";
function goto(url, opts = {}) {
  {
    throw new Error("Cannot call goto(...) on the server");
  }
}
const _contextKey = "$$_queryClient";
const getQueryClientContext = () => {
  const client = getContext(_contextKey);
  if (!client) {
    throw new Error("No QueryClient was found in Svelte context. Did you forget to wrap your component with QueryClientProvider?");
  }
  return client;
};
const setQueryClientContext = (client) => {
  setContext(_contextKey, client);
};
const _isRestoringContextKey = "$$_isRestoring";
const getIsRestoringContext = () => {
  try {
    const isRestoring = getContext(_isRestoringContextKey);
    return isRestoring ? isRestoring : readable(false);
  } catch (error) {
    return readable(false);
  }
};
export {
  getIsRestoringContext as a,
  getQueryClientContext as b,
  goto as g,
  setQueryClientContext as s
};
