// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HelpImagesEditor } from "./HelpImagesEditor";

import type { HelpImage } from "../types";

import { uploadRasterMedia } from "@/lib/uploadMedia";

vi.mock("@/lib/uploadMedia", () => ({ uploadRasterMedia: vi.fn() }));

const mockedUpload = vi.mocked(uploadRasterMedia);

interface FormShape {
  help_images: HelpImage[];
}

/** Mirrors how ProductEditPage/RequiredFieldsEditor actually wire this up —
 *  a real react-hook-form control, submitted through handleSubmit, so an
 *  assertion on "what the form submits" exercises the exact same path the
 *  page does. */
function Harness({ initial = [] }: { initial?: HelpImage[] }) {
  const { control, register, handleSubmit } = useForm<FormShape>({
    defaultValues: { help_images: initial },
  });
  const [submitted, setSubmitted] = useState<HelpImage[] | null>(null);
  return (
    <form
      onSubmit={handleSubmit((values) => {
        setSubmitted(values.help_images);
      })}
    >
      <HelpImagesEditor
        // ProductEditPage does the same cast when handing its `form.control`
        // down through RequiredFieldsEditor — the component's props are
        // typed `Control<any>` because the concrete form shape lives one
        // level up, and `exactOptionalPropertyTypes` rejects the otherwise-
        // compatible concrete `Control<FormShape>` here without it.
        /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
        control={control as any}
        /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
        register={register as any}
        name="help_images"
      />
      <button type="submit">Сохранить</button>
      {submitted && <div data-testid="submitted">{JSON.stringify(submitted)}</div>}
    </form>
  );
}

function makeFile(name: string): File {
  return new File(["x"], name, { type: "image/png" });
}

function fileInput(): HTMLInputElement {
  const input = document.querySelector('input[type="file"]');
  if (!input) throw new Error("file input not found");
  return input as HTMLInputElement;
}

function image(n: string): HelpImage {
  return { url: `https://cdn.yupay.uz/field-help/${n}.png`, caption: { ru: "", en: "", uz: "" } };
}

function readSubmitted(): HelpImage[] {
  const text = screen.getByTestId("submitted").textContent;
  // Known-shape JSON: the Harness only ever JSON.stringifies `HelpImage[]` into this node.
  return text ? (JSON.parse(text) as HelpImage[]) : [];
}

afterEach(() => {
  vi.resetAllMocks();
});

describe("HelpImagesEditor", () => {
  it("uploads a file, shows the thumbnail, and includes the URL in what the form submits", async () => {
    mockedUpload.mockResolvedValue("https://cdn.yupay.uz/field-help/new.png");
    render(<Harness />);

    const file = makeFile("screenshot.png");
    fireEvent.change(fileInput(), { target: { files: [file] } });

    // alt="" makes these presentational, not role="img" — see Thumb.test.tsx.
    await waitFor(() => {
      expect(screen.getAllByRole("presentation", { hidden: true })).toHaveLength(1);
    });
    expect(screen.getByRole("presentation", { hidden: true })).toHaveAttribute(
      "src",
      "https://cdn.yupay.uz/field-help/new.png",
    );
    expect(mockedUpload).toHaveBeenCalledWith("field_help_image", file);

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(screen.getByTestId("submitted")).toBeInTheDocument();
    });
    const submitted = readSubmitted();
    expect(submitted).toEqual([
      { url: "https://cdn.yupay.uz/field-help/new.png", caption: { ru: "", en: "", uz: "" } },
    ]);
  });

  it("hides the add control at 6 images and says why", () => {
    const six = ["a", "b", "c", "d", "e", "f"].map(image);
    render(<Harness initial={six} />);

    expect(screen.queryByLabelText(/Добавить изображение/i)).not.toBeInTheDocument();
    expect(screen.getByText(/Достигнут максимум 6 изображений на поле/i)).toBeInTheDocument();
  });

  it("counts an in-flight upload against the cap so a second quick pick cannot exceed 6", async () => {
    // The bug: an upload still in flight hasn't appended its row yet, so
    // `rows.length` alone under-counts what's about to exist — two quick
    // picks could each see a free slot and both proceed, landing past 6.
    // A Promise executor runs synchronously, so `resolveUpload` is assigned
    // before `deferred()` returns — the `!` just tells TS to trust that.
    let resolveUpload!: (url: string) => void;
    mockedUpload.mockImplementation(
      () =>
        new Promise<string>((resolve) => {
          resolveUpload = resolve;
        }),
    );
    const five = ["a", "b", "c", "d", "e"].map(image);
    render(<Harness initial={five} />);

    fireEvent.change(fileInput(), { target: { files: [makeFile("f.png")] } });

    // One upload in flight against 5 settled rows already fills the cap —
    // the add control must reflect that before the upload even resolves.
    await waitFor(() => {
      expect(screen.queryByLabelText(/Добавить изображение/i)).not.toBeInTheDocument();
    });
    expect(screen.getByText(/Достигнут максимум 6 изображений на поле/i)).toBeInTheDocument();

    resolveUpload("https://cdn.yupay.uz/field-help/f.png");
    await waitFor(() => {
      expect(screen.getAllByRole("presentation", { hidden: true })).toHaveLength(6);
    });
    // Still capped, not 7 — nothing snuck in while the upload was pending.
    expect(screen.getAllByRole("presentation", { hidden: true })).toHaveLength(6);
  });

  it("reflects a reorder and a removal in what the form submits", async () => {
    const three = ["a", "b", "c"].map(image);
    render(<Harness initial={three} />);

    // a, b, c -> move "a" (row 1) down -> b, a, c
    fireEvent.click(screen.getByRole("button", { name: "Переместить изображение 1 ниже" }));
    // remove what is now the last row ("c", still row 3)
    fireEvent.click(screen.getByRole("button", { name: "Удалить изображение 3" }));

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));

    await waitFor(() => {
      expect(screen.getByTestId("submitted")).toBeInTheDocument();
    });
    const submitted = readSubmitted();
    expect(submitted.map((i) => i.url)).toEqual([image("b").url, image("a").url]);
  });

  it("surfaces a failed upload and adds nothing", async () => {
    mockedUpload.mockRejectedValue(new Error("R2 upload failed: 500 Internal Server Error"));
    render(<Harness />);

    const file = makeFile("broken.png");
    fireEvent.change(fileInput(), { target: { files: [file] } });

    await screen.findByText(/R2 upload failed: 500 Internal Server Error/);
    expect(screen.queryAllByRole("presentation", { hidden: true })).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Сохранить" }));
    await waitFor(() => {
      expect(screen.getByTestId("submitted")).toBeInTheDocument();
    });
    const submitted = readSubmitted();
    expect(submitted).toEqual([]);
  });
});
