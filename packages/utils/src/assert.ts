/**
 * Exhaustiveness helper for `switch` statements. Pass the value from the `default` arm.
 * If the type-checker reaches this function, a case is unhandled.
 */
export function assertNever(value: never): never {
  throw new Error(`Unhandled discriminant: ${JSON.stringify(value)}`);
}
