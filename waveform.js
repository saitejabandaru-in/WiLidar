/**
 * WiLidar Real-Time Waveform Oscilloscope Component (Chart.js)
 * Implements linear gradient area fills and grid lines optimization for premium visuals.
 */
class WaveformOscilloscope {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext("2d");
        this.maxPoints = 80; // Window size of data points on screen
        
        // Define hex color codes matching root theme variables
        this.hexColors = {
            gold: "#c5a059",
            platinum: "#1d1d1f",
            silver: "#86868b"
        };
        
        this.chart = this.initChart();
    }
    
    initChart() {
        // Create linear gradient fills for glowing oscilloscope effect
        // Gradient 1 (Gold)
        const gradGold = this.ctx.createLinearGradient(0, 0, 0, 160);
        gradGold.addColorStop(0, "rgba(197, 160, 89, 0.2)");
        gradGold.addColorStop(1, "rgba(197, 160, 89, 0.0)");
        
        // Gradient 2 (Platinum/Charcoal)
        const gradPlatinum = this.ctx.createLinearGradient(0, 0, 0, 160);
        gradPlatinum.addColorStop(0, "rgba(29, 29, 31, 0.12)");
        gradPlatinum.addColorStop(1, "rgba(29, 29, 31, 0.0)");
        
        // Gradient 3 (Silver/Grey)
        const gradSilver = this.ctx.createLinearGradient(0, 0, 0, 160);
        gradSilver.addColorStop(0, "rgba(134, 134, 139, 0.1)");
        gradSilver.addColorStop(1, "rgba(134, 134, 139, 0.0)");
        
        return new Chart(this.ctx, {
            type: "line",
            data: {
                labels: [], // Streaming Timestamps
                datasets: [
                    {
                        label: "CSI Subcarrier PCA 1",
                        borderColor: this.hexColors.gold,
                        backgroundColor: gradGold,
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.4, // Smooth interpolation curves
                        fill: true,
                        data: []
                    },
                    {
                        label: "CSI Subcarrier PCA 2",
                        borderColor: this.hexColors.platinum,
                        backgroundColor: gradPlatinum,
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.4,
                        fill: true,
                        data: []
                    },
                    {
                        label: "CSI Subcarrier PCA 3",
                        borderColor: this.hexColors.silver,
                        backgroundColor: gradSilver,
                        borderWidth: 1.5,
                        pointRadius: 0,
                        tension: 0.4,
                        fill: true,
                        data: []
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        position: "top",
                        align: "end",
                        labels: {
                            color: "#515154", // var(--text-secondary)
                            font: {
                                family: "Outfit",
                                size: 10,
                                weight: 400
                            },
                            boxWidth: 6,
                            boxHeight: 6,
                            usePointStyle: true,
                            padding: 12
                        }
                    },
                    tooltip: {
                        enabled: false // Performance optimization for real-time streams
                    }
                },
                scales: {
                    x: {
                        display: false,
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        display: true,
                        grid: {
                            color: "rgba(0, 0, 0, 0.06)" // Subtle coordinate grid lines
                        },
                        border: {
                            dash: [3, 3] // Dashed axis borders
                        },
                        ticks: {
                            color: "#86868b", // var(--text-muted)
                            font: {
                                family: "Share Tech Mono",
                                size: 9,
                                weight: 400
                            },
                            padding: 6
                        },
                        min: -10,
                        max: 10
                    }
                },
                animations: {
                    // Disable animations for 60fps scrolling performance
                    duration: 0
                }
            }
        });
    }
    
    appendData(timestamp, values) {
        const labels = this.chart.data.labels;
        
        // Push timestamp label
        const timeStr = new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        labels.push(timeStr);
        
        // Push raw amplitude values to each dataset stream
        for (let i = 0; i < 3; i++) {
            this.chart.data.datasets[i].data.push(values[i]);
        }
        
        // Window sliding logic to prevent memory leaks and keep rendering fast
        if (labels.length > this.maxPoints) {
            labels.shift();
            for (let i = 0; i < 3; i++) {
                this.chart.data.datasets[i].data.shift();
            }
        }
        
        // Update line drawing
        this.chart.update("none");
    }
}
