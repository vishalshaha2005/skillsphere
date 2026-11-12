(() => {
  const storageKey = "skillsphere_theme";
  const themeColor = theme => {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.content = theme === "dark" ? "#090f1d" : "#f4f8ff";
  };
  const apply = value => {
    const theme = value === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    themeColor(theme);
    return theme;
  };
  const get = () => apply(localStorage.getItem(storageKey));
  const set = theme => {
    if (theme !== "light" && theme !== "dark") throw new TypeError("Theme must be light or dark.");
    localStorage.setItem(storageKey, theme);
    return apply(theme);
  };
  const toggle = () => set(get() === "dark" ? "light" : "dark");

  apply(localStorage.getItem(storageKey));
  window.addEventListener("storage", event => {
    if (event.key === storageKey) apply(event.newValue);
  });
  window.SkillSphereTheme = Object.freeze({ get, set, toggle });
})();
