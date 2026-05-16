# @yupay/ui

Shared design system: shadcn-style primitives, theme-aware components, and CVA-driven
variants. Both `apps/web` and `apps/miniapp` import from here.

- Design tokens live in `@yupay/config-tailwind/tokens` (CSS custom properties consumed via
  Tailwind v4's `@theme`).
- All variants use `class-variance-authority` (`cva`); no long `clsx` ladders.
- Icons: `lucide-react` only.

Adding a component:

```
src/components/<Name>/
  Name.tsx
  Name.stories.tsx   # optional once Storybook lands
  Name.test.tsx
  index.ts
```
