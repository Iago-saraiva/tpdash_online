import type { Aviso } from "../tipos";

export default function Avisos({ avisos }: { avisos: Aviso[] }) {
  return (
    <div className="adm-avisos" role="status" aria-live="polite">
      {avisos.map((a) => <div key={a.id} className={"aviso " + a.tipo}>{a.texto}</div>)}
    </div>
  );
}
