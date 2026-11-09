// Dados que o Flask coloca na página (usuário, empresa, menu...). Ficam num <script type="application/json">.
export interface Usuario {
  nome: string;
  admin: boolean;
  modulos: string[];
}

export interface Pagina {
  chave: string;
  url: string;
  titulo: string;
}

export interface Banco {
  id: string;
  nome: string;
}

export interface DadosPagina {
  tela: string;                 // "login", "trocar_senha" ou o módulo (inicio, movimentos...)
  titulo: string;
  empresa: string;
  modo: string;                 // "demo" mostra o selo de demonstração
  csrf: string;
  usuario?: Usuario;
  paginas?: Pagina[];           // telas que o usuário pode abrir, na ordem do menu
  react?: string[];             // telas que já estão em React (as outras abrem a página antiga)
  admin_link?: boolean;         // mostra "Administração" no menu
  bancos?: Banco[];             // empresas do usuário (troca no topo)
  banco_atual?: string;
  // tela de login
  erro?: string;
  lembrar?: boolean;
  bancos_login?: Banco[];
  banco_sel?: string;
}

const el = document.getElementById("tpdash-dados");
export const DADOS: DadosPagina = el ? JSON.parse(el.textContent || "{}") : ({ tela: "", titulo: "", empresa: "", modo: "", csrf: "" });
