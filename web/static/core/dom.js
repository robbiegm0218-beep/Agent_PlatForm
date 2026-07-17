window.AgentElements = new Proxy({}, {
  get(_target, property) {
    return typeof property === "string" ? document.querySelector(`#${property}`) : undefined;
  },
});
