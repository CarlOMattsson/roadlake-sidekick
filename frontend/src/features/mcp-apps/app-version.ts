// The version the app announces in the host handshake. It is the `version` of frontend/package.json, which
// tools/check-version-sync.py keeps equal to the release version in backend/pyproject.toml. Importing the one
// name lets the bundler drop the rest of the file.
import { version } from "../../../package.json";

export const APP_VERSION: string = version;
