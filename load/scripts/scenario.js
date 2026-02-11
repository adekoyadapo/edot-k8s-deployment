import http from "k6/http";
import { sleep } from "k6";

export const options = {
  vus: 200,
  duration: "5m",
};

const target = __ENV.TARGET_URL || "http://frontend:8080/";

export default function () {
  http.get(target);
  http.get(`${target}simulate`);
  http.post(`${target.replace(/\/$/, "")}/api/items`, JSON.stringify({ key: "k6", value: "v1" }), {
    headers: { "Content-Type": "application/json" },
  });
  http.get(`${target.replace(/\/$/, "")}/api/items/k6`);
  http.put(`${target.replace(/\/$/, "")}/api/items/k6`, JSON.stringify({ key: "k6", value: "v2" }), {
    headers: { "Content-Type": "application/json" },
  });
  http.del(`${target.replace(/\/$/, "")}/api/items/k6`);
  http.get(`${target.replace(/\/$/, "")}/api/slow`);
  sleep(0.01);
}
