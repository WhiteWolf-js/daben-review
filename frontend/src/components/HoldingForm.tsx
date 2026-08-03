import { useState } from "react";
import { Button, Stack, TextField } from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import dayjs from "dayjs";
import { addHolding } from "../api";

const empty = { code: "", name: "", buy_price: "", buy_date: "", buy_boards: "" };

/** 添加打板持仓(放折叠区,录入是低频动作)。成功后回调父级刷新列表。 */
export default function HoldingForm({ onAdded }: { onAdded?: () => void }) {
  const [form, setForm] = useState({ ...empty });

  const submit = () => {
    if (!form.code.trim() || !form.buy_price) return;
    addHolding({
      code: form.code.trim(),
      name: form.name.trim(),
      buy_price: Number(form.buy_price),
      buy_date: form.buy_date.trim(),
      buy_boards: Number(form.buy_boards || 0),
    }).then(() => {
      setForm({ ...empty });
      onAdded?.();
    });
  };

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1}>
        <TextField
          size="small"
          label="代码"
          value={form.code}
          onChange={(e) => setForm({ ...form, code: e.target.value })}
          sx={{ width: 110 }}
        />
        <TextField
          size="small"
          label="名称"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          fullWidth
        />
      </Stack>
      <Stack direction="row" spacing={1}>
        <TextField
          size="small"
          label="成本价"
          type="number"
          value={form.buy_price}
          onChange={(e) => setForm({ ...form, buy_price: e.target.value })}
          sx={{ width: 130 }}
        />
        <TextField
          size="small"
          label="买入板数"
          type="number"
          value={form.buy_boards}
          onChange={(e) => setForm({ ...form, buy_boards: e.target.value })}
          sx={{ width: 130 }}
        />
        <DatePicker
          label="买入日"
          value={
            form.buy_date
              ? dayjs(`${form.buy_date.slice(0, 4)}-${form.buy_date.slice(4, 6)}-${form.buy_date.slice(6)}`)
              : null
          }
          onChange={(v) => setForm({ ...form, buy_date: v ? v.format("YYYYMMDD") : "" })}
          format="YYYY-MM-DD"
          maxDate={dayjs()}
          slotProps={{ textField: { size: "small", fullWidth: true } }}
        />
      </Stack>
      <Button variant="contained" size="small" onClick={submit} disabled={!form.code.trim() || !form.buy_price}>
        添加
      </Button>
    </Stack>
  );
}
