// eval(input) is mentioned in documentation, but never called.
export function safeParse(input: string) {
  return JSON.parse(input)
}
