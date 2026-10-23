// Build-time isolation: the only shared demo asset is the visual design stylesheet.
export function assertProtectedModules(modules: Iterable<string>, demoRoot: string): void {
  const demo = demoRoot.replaceAll('\\', '/')
  for (const id of modules) {
    const path = id.replaceAll('\\', '/').split('?')[0]!
    if (path.startsWith(`${demo}/`) && path !== `${demo}/design.css`) {
      throw new Error('Protected builds cannot import the demo application or its fixtures.')
    }
  }
}
