/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 项目文档链接(个人内网文档,不进仓库)。留空则页脚不显示该链接。配在 `.env.local`。 */
  readonly VITE_DOC_URL?: string;
  /** MUI X Pro 授权码。商业凭证,**只能配在 `.env.local`**,不进仓库。留空则不调 setLicenseKey。 */
  readonly VITE_MUI_LICENSE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
