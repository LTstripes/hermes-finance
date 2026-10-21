function projectPattern(filter: string): RegExp {
  const expression = filter
    .split("*")
    .map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
    .join(".*");
  return new RegExp(`^${expression}$`, "i");
}

export function selectPlaywrightProjects(names: string[], filters: string[]): string[] {
  const matches = filters.map((filter) => ({
    filter,
    names: names.filter((name) => projectPattern(filter).test(name)),
  }));
  const unknown = matches.filter(({ names: matchedNames }) => matchedNames.length === 0);
  if (unknown.length) {
    const requested = unknown.map(({ filter }) => JSON.stringify(filter)).join(", ");
    throw new Error(
      `Unknown Playwright project name(s): ${requested}. Valid project names: ${names.join(", ")}`,
    );
  }
  return names.filter((name) =>
    matches.some(({ names: matchedNames }) => matchedNames.includes(name)),
  );
}
