/**
 * WiLidar Floor Plan SVG Coordinate Renderer
 * Implements 60fps LERP tracking interpolation, real-time RF propagation visuals,
 * and high-end architectural coordinate rulers.
 */
class FloorPlan {
    constructor(svgId) {
        this.svg = document.getElementById(svgId);
        this.roomsGroup = document.getElementById("rooms-group");
        this.nodesGroup = document.getElementById("nodes-group");
        this.trackerGroup = document.getElementById("tracker-group");
        this.rfGroup = document.getElementById("rf-wave-propagation");
        
        // Dynamic group for multi-person rendering
        this.peopleGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
        this.peopleGroup.id = "people-group";
        this.svg.appendChild(this.peopleGroup);
        
        // Coordinate Grid Scales: 52 pixels = 1 meter (fits 6m x 6m inside 600x500 box beautifully)
        this.scale = 55.0;
        
        // Floorplan offset variables: Anchors Bottom-Left Room corner in SVG space
        this.xOffset = 130.0;
        this.yOffset = 410.0;
        
        // Real-time animation loop variables
        this.activeTargets = {}; // Map of targetId -> state mapping
        this.nodesList = [];     // Cached list of nodes geometry
        this.waveTime = 0.0;
        
        // Run Default Layout initialization
        this.initDemoLayout();
        
        // Start high-performance 60fps SVG animation render loop
        requestAnimationFrame(() => this.renderFrame());
    }
    
    initDemoLayout() {
        const demoRooms = [
            { id: 1, name: "Sensing Volume: Room 01", width_m: 6.0, height_m: 6.0 }
        ];
        this.nodesList = [
            { id: 1001, x: 0.5, y: 0.5, room_id: 1 },
            { id: 1002, x: 5.5, y: 5.5, room_id: 1 }
        ];
        
        this.drawRooms(demoRooms);
        this.drawNodes(this.nodesList);
    }
    
    // Convert physical meters (bottom-left origin) to SVG coordinate system
    mToPx(x_m, y_m) {
        const px_x = this.xOffset + (x_m * this.scale);
        const px_y = this.yOffset - (y_m * this.scale); // Invert Y because SVG coordinates increase downwards
        return { x: px_x, y: px_y };
    }
    
    drawRooms(rooms) {
        this.roomsGroup.innerHTML = "";
        rooms.forEach(room => {
            const width_px = room.width_m * this.scale;
            const height_px = room.height_m * this.scale;
            
            // Draw Room Outline
            const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
            rect.setAttribute("class", "svg-room occupied");
            rect.setAttribute("x", this.xOffset);
            rect.setAttribute("y", this.yOffset - height_px);
            rect.setAttribute("width", width_px);
            rect.setAttribute("height", height_px);
            rect.setAttribute("rx", "4"); // Sharp, elegant corner radius
            rect.setAttribute("ry", "4");
            rect.id = `room-${room.id}`;
            this.roomsGroup.appendChild(rect);
            
            // Draw Room Title
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
            text.setAttribute("class", "svg-room-label");
            text.setAttribute("x", this.xOffset + width_px / 2.0);
            text.setAttribute("y", (this.yOffset - height_px) + 24);
            text.setAttribute("text-anchor", "middle");
            text.textContent = room.name;
            this.roomsGroup.appendChild(text);

            // Draw coordinate axis ticks along left and bottom sides of the room (0.0m to 6.0m)
            // Bottom ticks (X axis)
            for (let x_m = 0; x_m <= room.width_m; x_m += 1.0) {
                const px = this.mToPx(x_m, 0);
                
                // Tick line
                const tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
                tick.setAttribute("x1", px.x);
                tick.setAttribute("y1", px.y);
                tick.setAttribute("x2", px.x);
                tick.setAttribute("y2", px.y + 6);
                tick.setAttribute("stroke", "rgba(197, 160, 89, 0.35)");
                tick.setAttribute("stroke-width", "1");
                this.roomsGroup.appendChild(tick);
                
                // Label
                const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
                label.setAttribute("x", px.x);
                label.setAttribute("y", px.y + 18);
                label.setAttribute("text-anchor", "middle");
                label.setAttribute("fill", "var(--text-secondary)");
                label.setAttribute("font-family", "Share Tech Mono, monospace");
                label.setAttribute("font-size", "9px");
                label.textContent = `${x_m.toFixed(1)}m`;
                this.roomsGroup.appendChild(label);
            }
            
            // Left ticks (Y axis)
            for (let y_m = 0; y_m <= room.height_m; y_m += 1.0) {
                const px = this.mToPx(0, y_m);
                
                // Tick line
                const tick = document.createElementNS("http://www.w3.org/2000/svg", "line");
                tick.setAttribute("x1", px.x);
                tick.setAttribute("y1", px.y);
                tick.setAttribute("x2", px.x - 6);
                tick.setAttribute("y2", px.y);
                tick.setAttribute("stroke", "rgba(197, 160, 89, 0.35)");
                tick.setAttribute("stroke-width", "1");
                this.roomsGroup.appendChild(tick);
                
                // Label
                const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
                label.setAttribute("x", px.x - 12);
                label.setAttribute("y", px.y + 3);
                label.setAttribute("text-anchor", "end");
                label.setAttribute("fill", "var(--text-secondary)");
                label.setAttribute("font-family", "Share Tech Mono, monospace");
                label.setAttribute("font-size", "9px");
                label.textContent = `${y_m.toFixed(1)}m`;
                this.roomsGroup.appendChild(label);
            }
        });
    }
    
    drawNodes(nodes) {
        this.nodesGroup.innerHTML = "";
        this.nodesList = nodes; // Update local geometry cache
        
        nodes.forEach(node => {
            const px = this.mToPx(node.x, node.y);
            
            // Draw circle representing nodes
            const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            circle.setAttribute("class", "svg-node");
            circle.setAttribute("cx", px.x);
            circle.setAttribute("cy", px.y);
            circle.setAttribute("r", "8");
            circle.id = `node-svg-${node.id}`;
            
            // Style based on TX Master vs RX sub-nodes (Gold vs Platinum theme)
            if (node.id === 1001) {
                circle.setAttribute("fill", "var(--accent-gold)");
                circle.setAttribute("stroke", "var(--bg-color)");
                circle.setAttribute("stroke-width", "2");
            } else {
                circle.setAttribute("fill", "var(--text-primary)");
                circle.setAttribute("stroke", "var(--bg-color)");
                circle.setAttribute("stroke-width", "2");
            }
            
            this.nodesGroup.appendChild(circle);
            
            // Draw text label above node
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
            text.setAttribute("class", "svg-node-label");
            text.setAttribute("x", px.x);
            text.setAttribute("y", px.y - 14);
            text.setAttribute("text-anchor", "middle");
            text.textContent = node.id === 1001 ? "TX MASTER" : `RX NODE ${node.id}`;
            this.nodesGroup.appendChild(text);
        });
    }
    
    /**
     * Interface to update coordinates map. Stores target values to LERP inside animation frame loop.
     */
    updateMultiPositions(trackedPeople, activeNodes) {
        if (activeNodes && activeNodes.length > 0) {
            this.nodesList = activeNodes;
            this.drawNodes(activeNodes);
        }
        
        // Handle empty targets list
        if (!trackedPeople || trackedPeople.length === 0) {
            this.activeTargets = {};
            this.peopleGroup.innerHTML = "";
            return;
        }
        
        // Track list of incoming IDs
        const activeIds = new Set();
        
        trackedPeople.forEach(person => {
            const id = person.id;
            activeIds.add(id);
            
            if (!this.activeTargets[id]) {
                // Initialize target details
                this.activeTargets[id] = {
                    currentX: person.x_meters,
                    currentY: person.y_meters,
                    targetX: person.x_meters,
                    targetY: person.y_meters,
                    uncertainty: person.uncertainty,
                    opacity: 0.0 // Fade in
                };
            } else {
                // Update target coordinate indices
                this.activeTargets[id].targetX = person.x_meters;
                this.activeTargets[id].targetY = person.y_meters;
                this.activeTargets[id].uncertainty = person.uncertainty;
            }
        });
        
        // Clear targets that are no longer active
        for (const id in this.activeTargets) {
            if (!activeIds.has(parseInt(id))) {
                delete this.activeTargets[id];
            }
        }
    }
    
    hideTracker() {
        this.activeTargets = {};
        this.peopleGroup.innerHTML = "";
    }
    
    /**
     * Main 60fps visual rendering updates (concentric RF waves, LERP positions, multipath beams)
     */
    renderFrame() {
        this.waveTime += 0.04;
        this.rfGroup.innerHTML = "";
        
        // 1. Render propagating circular RF wavefront ripples from transmitter node (1001)
        const txNode = this.nodesList.find(n => n.id === 1001) || this.nodesList[0];
        const rxNodes = this.nodesList.filter(n => n.id !== 1001);
        
        if (txNode) {
            const txPx = this.mToPx(txNode.x, txNode.y);
            
            // Draw concentric wavefront ripples using champagne-gold theme
            for (let i = 0; i < 3; i++) {
                const phase = (this.waveTime * 24 + i * 80) % 240;
                const waveRadius = 15 + phase;
                const waveOpacity = Math.max(0, 0.1 * (1 - waveRadius / 240));
                
                const waveCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                waveCircle.setAttribute("cx", txPx.x);
                waveCircle.setAttribute("cy", txPx.y);
                waveCircle.setAttribute("r", waveRadius);
                waveCircle.setAttribute("fill", "none");
                waveCircle.setAttribute("stroke", "var(--accent-gold)");
                waveCircle.setAttribute("stroke-width", "1.0");
                waveCircle.setAttribute("stroke-opacity", waveOpacity);
                this.rfGroup.appendChild(waveCircle);
            }
            
            // Draw Line-of-Sight reference vectors between TX and RX nodes
            rxNodes.forEach(rx => {
                const rxPx = this.mToPx(rx.x, rx.y);
                const losLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
                losLine.setAttribute("x1", txPx.x);
                losLine.setAttribute("y1", txPx.y);
                losLine.setAttribute("x2", rxPx.x);
                losLine.setAttribute("y2", rxPx.y);
                losLine.setAttribute("stroke", "rgba(197, 160, 89, 0.1)");
                losLine.setAttribute("stroke-width", "1.5");
                this.rfGroup.appendChild(losLine);
            });
        }
        
        // 2. Perform LERP calculations and render targets
        this.peopleGroup.innerHTML = "";
        
        for (const idStr in this.activeTargets) {
            const id = parseInt(idStr);
            const target = this.activeTargets[id];
            
            // Perform Linear Interpolation for coordinates movement smoothness (60fps LERP)
            target.currentX += (target.targetX - target.currentX) * 0.12;
            target.currentY += (target.targetY - target.currentY) * 0.12;
            
            if (target.opacity < 1.0) target.opacity += 0.05;
            
            const px = this.mToPx(target.currentX, target.currentY);
            
            // Map styling colors based on target subject IDs to luxury theme tones
            let color, glowFilter;
            if (id === 1) {
                color = "var(--accent-gold)";
                glowFilter = "url(#glow-gold)";
            } else if (id === 2) {
                color = "var(--accent-platinum)";
                glowFilter = "url(#glow-platinum)";
            } else {
                color = "var(--text-secondary)";
                glowFilter = "url(#glow-gold)";
            }
            
            // Create target SVG container
            const tGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
            tGroup.setAttribute("opacity", target.opacity);
            
            // Draw Multipath Reflection Vectors from TX -> Target -> RX Node
            if (txNode && rxNodes.length > 0) {
                const txPx = this.mToPx(txNode.x, txNode.y);
                
                rxNodes.forEach(rx => {
                    const rxPx = this.mToPx(rx.x, rx.y);
                    
                    // TX to Target ray
                    const ray1 = document.createElementNS("http://www.w3.org/2000/svg", "line");
                    ray1.setAttribute("x1", txPx.x);
                    ray1.setAttribute("y1", txPx.y);
                    ray1.setAttribute("x2", px.x);
                    ray1.setAttribute("y2", px.y);
                    ray1.setAttribute("stroke", color);
                    ray1.setAttribute("stroke-opacity", "0.15");
                    ray1.setAttribute("stroke-width", "1.0");
                    ray1.setAttribute("stroke-dasharray", "3,3");
                    ray1.setAttribute("stroke-dashoffset", -this.waveTime * 10);
                    tGroup.appendChild(ray1);
                    
                    // Target to RX ray
                    const ray2 = document.createElementNS("http://www.w3.org/2000/svg", "line");
                    ray2.setAttribute("x1", px.x);
                    ray2.setAttribute("y1", px.y);
                    ray2.setAttribute("x2", rxPx.x);
                    ray2.setAttribute("y2", rxPx.y);
                    ray2.setAttribute("stroke", color);
                    ray2.setAttribute("stroke-opacity", "0.15");
                    ray2.setAttribute("stroke-width", "1.0");
                    ray2.setAttribute("stroke-dasharray", "3,3");
                    ray2.setAttribute("stroke-dashoffset", -this.waveTime * 10);
                    tGroup.appendChild(ray2);
                });
            }
            
            // Draw Uncertainty Range Circle
            const uCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            uCircle.setAttribute("cx", px.x);
            uCircle.setAttribute("cy", px.y);
            const radius = Math.max(12, target.uncertainty * this.scale);
            uCircle.setAttribute("r", radius);
            uCircle.setAttribute("fill", color);
            uCircle.setAttribute("fill-opacity", "0.02");
            uCircle.setAttribute("stroke", color);
            uCircle.setAttribute("stroke-opacity", "0.2");
            uCircle.setAttribute("stroke-width", "1.0");
            uCircle.setAttribute("stroke-dasharray", "2,2");
            tGroup.appendChild(uCircle);
            
            // Draw Outer Blur Glow Element
            const glow = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            glow.setAttribute("cx", px.x);
            glow.setAttribute("cy", px.y);
            glow.setAttribute("r", "8");
            glow.setAttribute("fill", color);
            glow.setAttribute("filter", glowFilter);
            tGroup.appendChild(glow);
            
            // Draw Core white pin
            const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
            dot.setAttribute("cx", px.x);
            dot.setAttribute("cy", px.y);
            dot.setAttribute("r", "4.5");
            dot.setAttribute("fill", "#ffffff");
            tGroup.appendChild(dot);
            
            // Draw Target label overlay text (e.g. "P1")
            const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
            text.setAttribute("x", px.x);
            text.setAttribute("y", px.y - 16);
            text.setAttribute("text-anchor", "middle");
            text.setAttribute("fill", "#ffffff");
            text.setAttribute("font-size", "10px");
            text.setAttribute("font-weight", "600");
            text.setAttribute("style", "text-shadow: 0 1px 3px rgba(0,0,0,0.95); font-family: Outfit, sans-serif; letter-spacing: -0.3px;");
            text.textContent = `P${id}`;
            tGroup.appendChild(text);
            
            // Draw physical coordinates text readout below target pin
            const coordText = document.createElementNS("http://www.w3.org/2000/svg", "text");
            coordText.setAttribute("x", px.x);
            coordText.setAttribute("y", px.y + radius + 15);
            coordText.setAttribute("text-anchor", "middle");
            coordText.setAttribute("fill", "var(--text-secondary)");
            coordText.setAttribute("font-size", "9px");
            coordText.setAttribute("font-family", "Share Tech Mono, monospace");
            coordText.setAttribute("style", "text-shadow: 0 1px 2px #ffffff; letter-spacing: 0.05em;");
            coordText.textContent = `[ ${target.currentX.toFixed(2)}m , ${target.currentY.toFixed(2)}m ]`;
            tGroup.appendChild(coordText);
            
            this.peopleGroup.appendChild(tGroup);
        }
        
        // Loop frame
        requestAnimationFrame(() => this.renderFrame());
    }
}
