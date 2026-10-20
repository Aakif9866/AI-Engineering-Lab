import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Empty } from "./components/ui";
import CacheCraft from "./pages/CacheCraft";
import EvidenceAtlas from "./pages/EvidenceAtlas";
import IntentForge from "./pages/IntentForge";
import MissionReplay from "./pages/MissionReplay";
import SignalLoop from "./pages/SignalLoop";
import TraceLens from "./pages/TraceLens";
import TrustBoundary from "./pages/TrustBoundary";
import Overview from "./pages/Overview";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Overview />} />
          <Route path="evidence-atlas" element={<EvidenceAtlas />} />
          <Route path="intentforge" element={<IntentForge />} />
          <Route path="cachecraft" element={<CacheCraft />} />
          <Route path="trustboundary" element={<TrustBoundary />} />
          <Route path="signalloop" element={<SignalLoop />} />
          <Route path="missionreplay" element={<MissionReplay />} />
          <Route path="tracelens" element={<TraceLens />} />
          <Route path="*" element={<Empty>Page not found. <Link className="link" to="/">Back to overview</Link></Empty>} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
