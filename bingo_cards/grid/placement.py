def build_default_grid_cells(
    image_width: int,
    image_height: int,
    grid_size: int,
) -> list[dict]:
    """Place a centered square grid in the lower portion of the template."""
    margin_x = max(20, int(image_width * 0.075))
    top_margin = max(20, int(image_height * 0.34))
    bottom_margin = max(20, int(image_height * 0.04))
    available_w = image_width - (2 * margin_x)
    available_h = image_height - top_margin - bottom_margin
    grid_span = min(available_w, available_h)
    start_x = margin_x + (available_w - grid_span) // 2
    start_y = top_margin + (available_h - grid_span) // 2
    cell_size = max(20, grid_span // grid_size)
    actual_span = cell_size * grid_size
    start_x += (grid_span - actual_span) // 2
    start_y += (grid_span - actual_span) // 2

    cells: list[dict] = []
    for row in range(grid_size):
        for col in range(grid_size):
            x1 = start_x + (col * cell_size)
            y1 = start_y + (row * cell_size)
            x2 = x1 + cell_size
            y2 = y1 + cell_size
            cells.append(
                {
                    "row": row,
                    "col": col,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "center_x": x1 + (cell_size // 2),
                    "center_y": y1 + (cell_size // 2),
                    "width": cell_size,
                    "height": cell_size,
                }
            )
    return cells


def build_uniform_grid_cells(
    grid_size: int,
    grid_x: int,
    grid_y: int,
    cell_width: int,
    cell_height: int,
) -> list[dict]:
    cell_width = max(20, cell_width)
    cell_height = max(20, cell_height)
    start_x = grid_x
    start_y = grid_y

    uniform_cells: list[dict] = []
    for row in range(grid_size):
        for col in range(grid_size):
            x1 = start_x + (col * cell_width)
            y1 = start_y + (row * cell_height)
            x2 = x1 + cell_width
            y2 = y1 + cell_height
            uniform_cells.append(
                {
                    "row": row,
                    "col": col,
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "center_x": x1 + (cell_width // 2),
                    "center_y": y1 + (cell_height // 2),
                    "width": cell_width,
                    "height": cell_height,
                }
            )
    return uniform_cells
